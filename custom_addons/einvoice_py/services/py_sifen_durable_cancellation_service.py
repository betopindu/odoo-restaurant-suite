import json
from contextlib import contextmanager
from dataclasses import dataclass

from psycopg2 import errors
from odoo import SUPERUSER_ID, api, fields
from odoo.exceptions import ValidationError
from odoo.modules import module


@dataclass(frozen=True)
class PySifenPreparedCancellation:
    transmission_id: int


class PySifenDurableCancellationService:
    """Commit cancellation evidence independently before and after its POST."""

    def __init__(self, env, *, cursor_factory=None):
        self.env = env
        self.cursor_factory = cursor_factory or env.registry.cursor

    @contextmanager
    def _cursor(self):
        if module.current_test:
            yield self.env.cr, False
            return
        with self.cursor_factory() as cr:
            yield cr, True

    def prepare(self, *, document, prepared_event, original_evidence_ids):
        identity = self._identity(document)
        with self._cursor() as (cr, independent):
            env = self._environment(cr, identity)
            durable_document = env["fiscal.document"].browse(document.id).exists()
            if not durable_document:
                raise ValidationError("SIFEN cancellation requires a committed fiscal document.")
            self._lock(cr, durable_document.id)
            self._validate(durable_document, identity)
            if env["fiscal.transmission"].sudo().search_count([
                ("document_id", "=", durable_document.id),
                ("transmission_type", "=", "cancel"),
                ("state", "in", ["pending", "sent", "manual_review", "accepted"]),
            ]):
                raise ValidationError(
                    "SIFEN cancellation already has active or accepted evidence."
                )
            attempt = env["fiscal.transmission"].sudo().create({
                "document_id": durable_document.id,
                "transmission_type": "cancel",
                "state": "pending",
                "country_code": "PY",
                "environment": identity["environment"],
                "country_identifier": identity["cdc"],
                "attempt_number": env["fiscal.transmission"].sudo().search_count([
                    ("document_id", "=", durable_document.id),
                    ("transmission_type", "=", "cancel"),
                ]) + 1,
                "endpoint_url": prepared_event.endpoint_url,
                "request_hash": prepared_event.request_hash,
                "started_at": fields.Datetime.now(),
                "metadata_json": self._metadata({
                    "service": "py_sifen_durable_cancellation",
                    "durability_phase": "prepared",
                    "post_started": False,
                    "ambiguous": False,
                    "event_id": prepared_event.event_id,
                    "original_evidence_ids": original_evidence_ids,
                }),
            })
            result = PySifenPreparedCancellation(attempt.id)
            if independent:
                cr.commit()
        return result

    def mark_post_started(self, *, transmission_id):
        with self._cursor() as (cr, independent):
            env = self._environment(cr, {})
            attempt = env["fiscal.transmission"].sudo().browse(transmission_id).exists()
            if not attempt or attempt.transmission_type != "cancel" or attempt.state != "pending":
                raise ValidationError("SIFEN durable cancellation attempt is unavailable.")
            metadata = self._read_metadata(attempt)
            metadata.update({
                "durability_phase": "post_started", "post_started": True,
                "ambiguous": True,
            })
            attempt.write({
                "state": "sent", "error_code": "ambiguous_event",
                "error_message": "SIFEN cancellation outcome is not yet known.",
                "error_type": "sifen_event", "metadata_json": self._metadata(metadata),
            })
            if independent:
                cr.commit()

    def finalize(self, *, transmission_id, result):
        with self._cursor() as (cr, independent):
            env = self._environment(cr, {})
            attempt = env["fiscal.transmission"].sudo().browse(transmission_id).exists()
            if not attempt or attempt.transmission_type != "cancel" or attempt.state != "sent":
                raise ValidationError("SIFEN durable cancellation attempt is unavailable.")
            if result.get("request_hash") != attempt.request_hash:
                raise ValidationError("SIFEN durable cancellation request hash is inconsistent.")
            state = "accepted" if result.get("accepted") else (
                "manual_review" if result.get("ambiguous") else "rejected"
            )
            metadata = self._read_metadata(attempt)
            metadata.update({
                "durability_phase": "finalized", "post_started": True,
                "ambiguous": bool(result.get("ambiguous")),
                "result_category": result.get("category") or "",
                "authority_protocol": result.get("authority_protocol") or "",
                "authority_timestamp": result.get("authority_timestamp") or "",
            })
            attempt.write({
                "state": state, "response_hash": result.get("response_hash") or "",
                "http_status": result.get("http_status") or 0,
                "duration_ms": result.get("duration_ms") or 0,
                "finished_at": fields.Datetime.now(),
                "authority_status_code": result.get("authority_code") or "",
                "authority_message": result.get("authority_message") or "",
                "error_code": "ambiguous_event" if result.get("ambiguous") else (
                    "" if result.get("accepted") else "event_rejected"
                ),
                "error_message": "SIFEN event requires manual reconciliation."
                if result.get("ambiguous") else "",
                "error_type": "sifen_event", "metadata_json": self._metadata(metadata),
            })
            if independent:
                cr.commit()

    @staticmethod
    def _identity(document):
        return {
            "tenant_id": document.tenant_id.id, "company_id": document.company_id.id,
            "environment": document.environment,
            "cdc": document.country_identifier or document.py_cdc,
        }

    @staticmethod
    def _validate(document, identity):
        if (
            document.state != "accepted"
            or document.tenant_id.id != identity["tenant_id"]
            or document.company_id.id != identity["company_id"]
            or document.environment != identity["environment"]
            or (document.country_identifier or document.py_cdc) != identity["cdc"]
        ):
            raise ValidationError("SIFEN durable cancellation identity is inconsistent.")

    @staticmethod
    def _lock(cr, document_id):
        try:
            cr.execute(
                "SELECT id FROM fiscal_document WHERE id = %s FOR UPDATE NOWAIT",
                [document_id],
            )
        except errors.LockNotAvailable:
            raise ValidationError("SIFEN cancellation is already in progress.") from None

    def _environment(self, cr, identity):
        context = dict(self.env.context)
        if identity.get("company_id"):
            context["allowed_company_ids"] = [identity["company_id"]]
        return api.Environment(cr, SUPERUSER_ID, context)

    @staticmethod
    def _metadata(values):
        return json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _read_metadata(attempt):
        try:
            value = json.loads(attempt.metadata_json or "{}")
        except (TypeError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}
