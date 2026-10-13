import json
from contextlib import contextmanager
from dataclasses import dataclass

from psycopg2 import errors
from odoo import SUPERUSER_ID, api, fields
from odoo.exceptions import ValidationError
from odoo.modules import module


@dataclass(frozen=True)
class PySifenPreparedInutilization:
    inutilization_id: int


class PySifenDurableInutilizationService:
    """Commit number-inutilization evidence independently around its POST."""

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

    def prepare(self, *, identity, prepared_event, reason):
        with self._cursor() as (cr, independent):
            env = self._environment(cr, identity)
            records = self._records(env, identity)
            self._lock(cr, records["timbrado"].id)
            self._validate(records, identity)
            if self._exact(env, identity):
                raise ValidationError(
                    "SIFEN inutilization already has evidence for this exact range."
                )
            if self._overlap(env, identity):
                raise ValidationError(
                    "SIFEN inutilization range overlaps existing evidence."
                )
            record = env["fiscal.py.inutilization"].sudo().create({
                "tenant_id": identity["tenant_id"],
                "company_id": identity["company_id"],
                "environment": identity["environment"],
                "adapter_config_id": identity["adapter_id"],
                "timbrado_id": identity["timbrado_id"],
                "establishment_id": identity["establishment_id"],
                "point_of_issue_id": identity["point_id"],
                "document_type": identity["document_type"],
                "number_from": identity["number_from"],
                "number_to": identity["number_to"],
                "occurred_on": identity["occurred_on"],
                "reason": reason,
                "event_id": prepared_event.event_id,
                "state": "pending",
                "endpoint_url": prepared_event.endpoint_url,
                "request_hash": prepared_event.request_hash,
                "started_at": fields.Datetime.now(),
                "metadata_json": self._metadata({
                    "service": "py_sifen_durable_inutilization",
                    "durability_phase": "prepared",
                    "post_started": False,
                    "ambiguous": False,
                    "event_id": prepared_event.event_id,
                }),
            })
            result = PySifenPreparedInutilization(record.id)
            if independent:
                cr.commit()
        return result

    def mark_post_started(self, *, inutilization_id):
        with self._cursor() as (cr, independent):
            env = self._environment(cr, {})
            record = env["fiscal.py.inutilization"].sudo().browse(
                inutilization_id
            ).exists()
            if not record or record.state != "pending":
                raise ValidationError(
                    "SIFEN durable inutilization attempt is unavailable."
                )
            metadata = self._read_metadata(record)
            metadata.update({
                "durability_phase": "post_started",
                "post_started": True,
                "ambiguous": True,
            })
            record.write({"metadata_json": self._metadata(metadata)})
            if independent:
                cr.commit()

    def finalize(self, *, inutilization_id, result):
        with self._cursor() as (cr, independent):
            env = self._environment(cr, {})
            record = env["fiscal.py.inutilization"].sudo().browse(
                inutilization_id
            ).exists()
            if not record or record.state != "pending":
                raise ValidationError(
                    "SIFEN durable inutilization attempt is unavailable."
                )
            if result.get("request_hash") != record.request_hash:
                raise ValidationError(
                    "SIFEN durable inutilization request hash is inconsistent."
                )
            state = "accepted" if result.get("accepted") else (
                "manual_review" if result.get("ambiguous") else "rejected"
            )
            metadata = self._read_metadata(record)
            metadata.update({
                "durability_phase": "finalized",
                "post_started": True,
                "ambiguous": bool(result.get("ambiguous")),
                "result_category": result.get("category") or "",
            })
            record.write({
                "state": state,
                "response_hash": result.get("response_hash") or "",
                "http_status": result.get("http_status") or 0,
                "duration_ms": result.get("duration_ms") or 0,
                "finished_at": fields.Datetime.now(),
                "authority_code": result.get("authority_code") or "",
                "authority_message": result.get("authority_message") or "",
                "authority_protocol": result.get("authority_protocol") or "",
                "authority_timestamp": result.get("authority_timestamp") or "",
                "metadata_json": self._metadata(metadata),
            })
            if independent:
                cr.commit()

    @staticmethod
    def _records(env, identity):
        definitions = {
            "adapter": ("fiscal.adapter.config", "adapter_id"),
            "timbrado": ("fiscal.py.timbrado", "timbrado_id"),
            "establishment": ("fiscal.py.establishment", "establishment_id"),
            "point": ("fiscal.py.point.of.issue", "point_id"),
        }
        records = {
            name: env[model].sudo().browse(identity[key]).exists()
            for name, (model, key) in definitions.items()
        }
        if not all(records.values()):
            raise ValidationError(
                "SIFEN inutilization requires committed fiscal configuration."
            )
        return records

    @staticmethod
    def _validate(records, identity):
        for record in records.values():
            if (
                record.tenant_id.id != identity["tenant_id"]
                or record.company_id.id != identity["company_id"]
            ):
                raise ValidationError("SIFEN inutilization identity is inconsistent.")
        if records["adapter"].environment != identity["environment"]:
            raise ValidationError("SIFEN inutilization identity is inconsistent.")

    @staticmethod
    def _domain(identity):
        return [
            ("tenant_id", "=", identity["tenant_id"]),
            ("company_id", "=", identity["company_id"]),
            ("environment", "=", identity["environment"]),
            ("timbrado_id", "=", identity["timbrado_id"]),
            ("establishment_id", "=", identity["establishment_id"]),
            ("point_of_issue_id", "=", identity["point_id"]),
            ("document_type", "=", identity["document_type"]),
        ]

    def _exact(self, env, identity):
        return env["fiscal.py.inutilization"].sudo().search(
            self._domain(identity) + [
                ("number_from", "=", identity["number_from"]),
                ("number_to", "=", identity["number_to"]),
            ], limit=1,
        )

    def _overlap(self, env, identity):
        return env["fiscal.py.inutilization"].sudo().search_count(
            self._domain(identity) + [
                ("number_from", "<=", identity["number_to"]),
                ("number_to", ">=", identity["number_from"]),
            ]
        )

    @staticmethod
    def _lock(cr, timbrado_id):
        try:
            cr.execute(
                "SELECT id FROM fiscal_py_timbrado WHERE id = %s FOR UPDATE NOWAIT",
                [timbrado_id],
            )
        except errors.LockNotAvailable:
            raise ValidationError(
                "SIFEN inutilization is already in progress for this timbrado."
            ) from None

    def _environment(self, cr, identity):
        context = dict(self.env.context)
        if identity.get("company_id"):
            context["allowed_company_ids"] = [identity["company_id"]]
        return api.Environment(cr, SUPERUSER_ID, context)

    @staticmethod
    def _metadata(values):
        return json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _read_metadata(record):
        try:
            value = json.loads(record.metadata_json or "{}")
        except (TypeError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}
