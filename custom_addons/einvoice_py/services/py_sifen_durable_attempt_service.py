import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from psycopg2 import errors

from odoo import SUPERUSER_ID, api, fields
from odoo.exceptions import ValidationError
from odoo.modules import module

from odoo.addons.einvoice_py.services.py_sifen_retry_eligibility_service import (
    PySifenRetryEligibilityService,
)


@dataclass(frozen=True)
class PySifenPreparedAttempt:
    """Identity committed by the durable transaction before caller work resumes."""

    transmission_id: int
    started_at: datetime


class PySifenDurableAttemptService:
    """Persist the SIFEN outbound boundary in an independent transaction."""

    TRANSMISSION_TYPE = "submit"
    HASH_RE = re.compile(r"[0-9a-f]{64}")
    SIGNING_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

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

    def prepare(
        self,
        *,
        document,
        endpoint_url="",
        manual_retry_authorization=None,
    ):
        """Create and commit an attempt before caller-owned artifact work."""
        document.ensure_one()
        identity = self._document_identity(document)
        with self._cursor() as (cr, independent):
            durable_env = self._environment(cr, identity)
            durable_document = durable_env["fiscal.document"].browse(
                identity["document_id"]
            ).exists()
            if not durable_document:
                raise ValidationError(
                    "SIFEN durable submission requires a committed fiscal document."
                )
            self._validate_document(durable_document, identity)
            self._lock_document(cr, durable_document.id)
            self._validate_no_active_attempt(
                durable_env,
                durable_document,
                identity,
                manual_retry_authorization=manual_retry_authorization,
            )
            retry_metadata = self._manual_retry_metadata(
                durable_env,
                durable_document,
                manual_retry_authorization,
            )
            transmission = durable_env["fiscal.transmission"].sudo().create({
                "document_id": durable_document.id,
                "transmission_type": self.TRANSMISSION_TYPE,
                "state": "pending",
                "country_code": "PY",
                "environment": identity["environment"],
                "country_identifier": identity["cdc"],
                "attempt_number": self._next_attempt_number(
                    durable_env, durable_document
                ),
                "endpoint_url": self._safe_endpoint(endpoint_url),
                "started_at": fields.Datetime.now(),
                "metadata_json": self._metadata_json({
                    "service": "py_sifen_durable_attempt",
                    "durability_phase": "prepared",
                    "post_started": False,
                    "ambiguous": False,
                    "resolution_status": "pre_post_incomplete",
                    **retry_metadata,
                }),
            })
            prepared = PySifenPreparedAttempt(
                transmission_id=transmission.id,
                started_at=transmission.started_at,
            )
            if independent:
                cr.commit()
        return prepared

    def mark_post_started(self, *, transmission_id, evidence):
        """Commit exact request identity immediately before transport invocation."""
        values = self._validated_evidence(evidence)
        with self._cursor() as (cr, independent):
            durable_env = self._environment(cr, values)
            transmission = durable_env["fiscal.transmission"].sudo().browse(
                transmission_id
            ).exists()
            self._validate_attempt(transmission, values, allowed_states=("pending",))
            metadata = self._metadata(transmission)
            metadata.update(values["metadata"])
            metadata.update({
                "service": "py_sifen_durable_attempt",
                "durability_phase": "post_started",
                "post_started": True,
                "ambiguous": True,
                "resolution_status": "remote_query_required",
            })
            transmission.write({
                "state": "sent",
                "request_hash": values["request_hash"],
                "endpoint_url": values["endpoint_url"],
                "signed_xml_sha256": values["signed_xml_sha256"],
                "qr_hash": values["qr_hash"],
                "error_code": "ambiguous_submission",
                "error_message": "SIFEN outbound request outcome is not yet known.",
                "metadata_json": self._metadata_json(metadata),
            })
            if independent:
                cr.commit()

    def finalize(
        self,
        *,
        transmission_id,
        values,
        result_metadata,
    ):
        """Commit normalized transport/authority evidence on the same attempt."""
        safe_values = self._final_values(values)
        with self._cursor() as (cr, independent):
            durable_env = self._environment(cr, safe_values)
            transmission = durable_env["fiscal.transmission"].sudo().browse(
                transmission_id
            ).exists()
            if not transmission or transmission.transmission_type != self.TRANSMISSION_TYPE:
                raise ValidationError("SIFEN durable submission attempt is unavailable.")
            if (
                safe_values.get("country_identifier")
                and safe_values["country_identifier"] != transmission.country_identifier
            ):
                raise ValidationError("SIFEN durable outcome CDC is inconsistent.")
            if (
                transmission.request_hash
                and safe_values.get("request_hash") != transmission.request_hash
            ):
                raise ValidationError("SIFEN durable request hash is inconsistent.")
            if (
                not module.current_test
                and safe_values.get("request_hash")
                and transmission.state != "sent"
            ):
                raise ValidationError(
                    "SIFEN durable outcome lacks committed pre-POST evidence."
                )
            metadata = self._metadata(transmission)
            metadata.update(self._safe_result_metadata(result_metadata))
            metadata.update({
                "service": "py_sifen_durable_attempt",
                "durability_phase": "completed",
                "post_started": bool(metadata.get("post_started")),
            })
            safe_values["metadata_json"] = self._metadata_json(metadata)
            transmission.write(safe_values)
            if independent:
                cr.commit()

    def recovery_status(self, transmission):
        """Classify restart-visible evidence without inferring a safe resend."""
        transmission.ensure_one()
        metadata = self._metadata(transmission)
        phase = metadata.get("durability_phase")
        post_started = bool(metadata.get("post_started"))
        if transmission.state in ("accepted", "rejected", "failed_final", "failed_retryable"):
            return "completed"
        if transmission.state == "pending" and phase == "prepared" and not post_started:
            return "prepared_not_posted"
        if transmission.state in ("sent", "manual_review") and post_started:
            return "outcome_unknown"
        return "manual_review_required"

    def abandon_prepared_not_posted(self, transmission):
        """Operator-confirm a prepared attempt whose POST marker was never committed."""
        transmission.ensure_one()
        transmission_id = transmission.id
        identity = {
            "company_id": transmission.document_id.company_id.id,
        }
        with self._cursor() as (cr, independent):
            durable_env = self._environment(cr, identity)
            durable = durable_env["fiscal.transmission"].sudo().browse(
                transmission_id
            ).exists()
            if self.recovery_status(durable) != "prepared_not_posted":
                raise ValidationError(
                    "Only a durable attempt proven not posted can be abandoned."
                )
            if durable.request_hash or durable.response_hash:
                raise ValidationError(
                    "Durable request evidence prevents pre-POST abandonment."
                )
            metadata = self._metadata(durable)
            metadata.update({
                "durability_phase": "completed",
                "post_started": False,
                "ambiguous": False,
                "resolution_status": "post_not_started",
            })
            durable.write({
                "state": "failed_final",
                "error_code": "pre_post_not_attempted",
                "error_message": "SIFEN POST was not started for this durable attempt.",
                "finished_at": fields.Datetime.now(),
                "metadata_json": self._metadata_json(metadata),
            })
            if independent:
                cr.commit()

    def _document_identity(self, document):
        cdc = (document.country_identifier or document.py_cdc or "").strip()
        if not cdc:
            raise ValidationError("SIFEN durable submission requires a CDC.")
        return {
            "document_id": document.id,
            "tenant_id": document.tenant_id.id,
            "company_id": document.company_id.id,
            "environment": document.environment,
            "country_code": (document.country_code or "").upper(),
            "cdc": cdc,
        }

    def _environment(self, cr, identity):
        company_id = identity.get("company_id")
        return api.Environment(
            cr,
            SUPERUSER_ID,
            {"allowed_company_ids": [company_id]} if company_id else {},
        )

    def _validate_document(self, document, identity):
        if (
            identity["country_code"] != "PY"
            or (document.country_code or "").upper() != "PY"
            or document.environment != identity["environment"]
            or document.tenant_id.id != identity["tenant_id"]
            or document.company_id.id != identity["company_id"]
            or (document.country_identifier or document.py_cdc or "").strip()
            != identity["cdc"]
        ):
            raise ValidationError("SIFEN durable submission document scope is invalid.")

    def _lock_document(self, cr, document_id):
        try:
            cr.execute(
                "SELECT id FROM fiscal_document WHERE id = %s FOR UPDATE NOWAIT",
                [document_id],
            )
            locked = cr.fetchone()
        except errors.LockNotAvailable:
            raise ValidationError(
                "SIFEN submission is already in progress for this document."
            ) from None
        if not locked:
            raise ValidationError("SIFEN durable submission document no longer exists.")

    def _validate_no_active_attempt(
        self,
        env,
        document,
        identity,
        *,
        manual_retry_authorization=None,
    ):
        transmissions = env["fiscal.transmission"].sudo()
        scope = [
            ("transmission_type", "=", self.TRANSMISSION_TYPE),
            ("country_code", "=", "PY"),
            ("environment", "=", identity["environment"]),
            ("tenant_id", "=", identity["tenant_id"]),
            ("company_id", "=", identity["company_id"]),
            ("country_identifier", "=", identity["cdc"]),
        ]
        if document.state == "accepted" or transmissions.search_count(
            scope + [("state", "=", "accepted")]
        ):
            raise ValidationError("An accepted SIFEN document cannot be submitted again.")
        active = transmissions.search(scope + [("state", "in", ("pending", "sent", "manual_review"))])
        if active.filtered(self._is_unresolved):
            if PySifenRetryEligibilityService(env).validate_authorization(
                document=document,
                authorization=manual_retry_authorization,
            ):
                return
            raise ValidationError(
                "SIFEN submission has unresolved durable evidence; reconciliation is required."
            )

    def _manual_retry_metadata(self, env, document, authorization):
        if authorization is None:
            return {}
        if not PySifenRetryEligibilityService(env).validate_authorization(
            document=document,
            authorization=authorization,
        ):
            return {}
        return {
            "manual_retry_evidence_type": authorization.evidence_type,
            "reconciled_submission_id": authorization.ambiguous_submission_id,
            "reconciliation_query_id": authorization.reconciliation_query_id,
            "local_failure_submission_id": authorization.local_failure_submission_id,
        }

    def _is_unresolved(self, transmission):
        metadata = self._metadata(transmission)
        if transmission.state in ("pending", "sent"):
            return True
        return (
            transmission.state == "manual_review"
            and metadata.get("resolution_status") not in ("accepted", "rejected")
        )

    def _next_attempt_number(self, env, document):
        previous = env["fiscal.transmission"].sudo().search(
            [("document_id", "=", document.id)],
            order="attempt_number desc,id desc",
            limit=1,
        )
        return (previous.attempt_number or 0) + 1

    def _validated_evidence(self, evidence):
        if not isinstance(evidence, dict):
            raise ValidationError("SIFEN durable request evidence is invalid.")
        required_hashes = (
            "request_hash",
            "payload_sha256",
            "unsigned_xml_sha256",
            "signed_xml_sha256",
            "qr_sha256",
            "rde_sha256",
        )
        for key in required_hashes:
            if not self.HASH_RE.fullmatch(str(evidence.get(key) or "")):
                raise ValidationError("SIFEN durable request evidence is incomplete.")
        qr_hash = str(evidence.get("qr_hash") or "")
        if not self.HASH_RE.fullmatch(qr_hash):
            raise ValidationError("SIFEN durable request evidence is incomplete.")
        attachment_ids = (
            "payload_attachment_id",
            "unsigned_xml_attachment_id",
            "signed_xml_attachment_id",
            "qr_attachment_id",
            "rde_attachment_id",
        )
        for key in attachment_ids:
            if not isinstance(evidence.get(key), int) or evidence[key] <= 0:
                raise ValidationError("SIFEN durable request evidence is incomplete.")
        signing_time = str(evidence.get("signing_time") or "")
        if not self.SIGNING_TIME_RE.fullmatch(signing_time):
            raise ValidationError("SIFEN durable signing evidence is invalid.")
        endpoint = self._safe_endpoint(evidence.get("endpoint_url"))
        if not endpoint:
            raise ValidationError("SIFEN durable endpoint evidence is invalid.")
        cdc = str(evidence.get("cdc") or "")
        if not re.fullmatch(r"\d{44}", cdc):
            raise ValidationError("SIFEN durable CDC evidence is invalid.")
        return {
            "document_id": evidence.get("document_id"),
            "tenant_id": evidence.get("tenant_id"),
            "company_id": evidence.get("company_id"),
            "environment": evidence.get("environment"),
            "country_code": "PY",
            "cdc": cdc,
            "request_hash": evidence["request_hash"],
            "endpoint_url": endpoint,
            "signed_xml_sha256": evidence["signed_xml_sha256"],
            "qr_hash": qr_hash,
            "metadata": {
                key: evidence[key]
                for key in (
                    *attachment_ids,
                    "payload_sha256",
                    "unsigned_xml_sha256",
                    "signed_xml_sha256",
                    "qr_sha256",
                    "rde_sha256",
                    "signing_time",
                    "digest_value",
                )
                if evidence.get(key) not in (None, "")
            },
        }

    def _validate_attempt(self, transmission, evidence, *, allowed_states):
        if (
            not transmission
            or transmission.state not in allowed_states
            or transmission.document_id.id != evidence["document_id"]
            or transmission.tenant_id.id != evidence["tenant_id"]
            or transmission.company_id.id != evidence["company_id"]
            or transmission.environment != evidence["environment"]
            or transmission.country_identifier != evidence["cdc"]
        ):
            raise ValidationError("SIFEN durable submission attempt scope is invalid.")

    def _final_values(self, values):
        allowed = {
            "state",
            "country_code",
            "environment",
            "country_identifier",
            "request_hash",
            "response_hash",
            "endpoint_url",
            "http_status",
            "duration_ms",
            "authority_status_code",
            "authority_message",
            "error_code",
            "error_message",
            "error_type",
            "signed_xml_sha256",
            "qr_hash",
            "started_at",
            "finished_at",
            "retry_state",
            "next_retry_at",
        }
        result = {key: value for key, value in values.items() if key in allowed}
        result["endpoint_url"] = self._safe_endpoint(result.get("endpoint_url"))
        return result

    def _safe_result_metadata(self, metadata):
        if not isinstance(metadata, dict):
            return {}
        allowed = (
            "pipeline_failed_stage",
            "submission_status",
            "retryable",
            "retry_category",
            "ambiguous",
            "resolution_status",
            "authority_receipt_ref",
            "authority_incident_type",
            "manual_retry_allowed",
            "automatic_retry_allowed",
            "diagnostic_code",
            "diagnostic_detail",
        )
        return {key: metadata[key] for key in allowed if key in metadata}

    def _metadata(self, transmission):
        try:
            value = json.loads(transmission.metadata_json or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _metadata_json(self, metadata):
        allowed = (
            "service",
            "durability_phase",
            "post_started",
            "pipeline_failed_stage",
            "submission_status",
            "retryable",
            "retry_category",
            "ambiguous",
            "resolution_status",
            "authority_receipt_ref",
            "authority_incident_type",
            "manual_retry_allowed",
            "automatic_retry_allowed",
            "diagnostic_code",
            "diagnostic_detail",
            "payload_attachment_id",
            "payload_sha256",
            "unsigned_xml_attachment_id",
            "unsigned_xml_sha256",
            "signed_xml_attachment_id",
            "signed_xml_sha256",
            "qr_attachment_id",
            "qr_sha256",
            "rde_attachment_id",
            "rde_sha256",
            "signing_time",
            "digest_value",
            "manual_retry_evidence_type",
            "reconciled_submission_id",
            "reconciliation_query_id",
            "local_failure_submission_id",
        )
        return json.dumps(
            {key: metadata[key] for key in allowed if metadata.get(key) not in (None, "")},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _safe_endpoint(self, value):
        parsed = urlsplit(str(value or ""))
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            return ""
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
