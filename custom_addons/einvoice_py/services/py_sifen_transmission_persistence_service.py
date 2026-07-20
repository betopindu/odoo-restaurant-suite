import json

from odoo import fields
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_submission_pipeline_service import (
    PySifenSubmissionPipelineService,
)


class PySifenTransmissionPersistenceService:
    """Persist SIFEN submission pipeline results without storing secrets."""

    TRANSMISSION_TYPE = "submit"

    def __init__(self, env, submission_pipeline_service=None):
        self.env = env
        self.submission_pipeline_service = (
            submission_pipeline_service or PySifenSubmissionPipelineService(env)
        )

    def submit_and_persist(self, **kwargs):
        document = kwargs.get("document")
        if not document:
            raise ValidationError("SIFEN transmission persistence requires a document.")
        document.ensure_one()
        self._validate_document(document)
        started_at = fields.Datetime.now()
        result = self._submit_for_environment(document=document, kwargs=kwargs)
        finished_at = fields.Datetime.now()
        transmission = self.persist_result(
            document=document,
            result=result,
            started_at=started_at,
            finished_at=finished_at,
        )
        return {
            "result": result,
            "transmission_id": transmission.id,
        }

    def persist_result(self, *, document, result, started_at=None, finished_at=None):
        document.ensure_one()
        self._validate_document(document)
        self._validate_result(result)
        started_at = started_at or fields.Datetime.now()
        finished_at = finished_at or fields.Datetime.now()
        values = self._transmission_values(
            document=document,
            result=result,
            started_at=started_at,
            finished_at=finished_at,
        )
        transmission = self._find_existing(document, result)
        if transmission:
            transmission.write(values)
            return transmission
        values["attempt_number"] = self._next_attempt_number(document)
        return self.env["fiscal.transmission"].sudo().create(values)

    def _validate_document(self, document):
        if (document.country_code or "").upper() != "PY":
            raise ValidationError("SIFEN transmission persistence requires a Paraguay document.")
        if document.environment not in ("test", "production"):
            raise ValidationError(
                "SIFEN transmission persistence requires a supported environment."
            )

    def _submit_for_environment(self, *, document, kwargs):
        if document.environment == "test":
            return self.submission_pipeline_service.submit_test(**kwargs)
        return self.submission_pipeline_service.submit_production(**kwargs)

    def _validate_result(self, result):
        if not isinstance(result, dict):
            raise ValidationError("SIFEN transmission persistence result must be a dictionary.")
        if not result.get("failed_stage") and not result.get("submission_status"):
            raise ValidationError(
                "SIFEN transmission persistence result must include a pipeline outcome."
            )

    def _transmission_values(self, *, document, result, started_at, finished_at):
        return {
            "document_id": document.id,
            "transmission_type": self.TRANSMISSION_TYPE,
            "state": self._state_from_result(result),
            "country_code": (document.country_code or "").upper(),
            "environment": document.environment,
            "country_identifier": result.get("cdc") or document.country_identifier or "",
            "request_hash": result.get("request_hash") or "",
            "response_hash": result.get("response_hash") or "",
            "authority_status_code": result.get("authority_code") or "",
            "authority_message": result.get("authority_message") or "",
            "error_code": result.get("failed_stage") or "",
            "error_message": result.get("error_message") or "",
            "error_type": "sifen_submission_pipeline" if result.get("failed_stage") else "",
            "signed_xml_sha256": result.get("signed_xml_sha256") or "",
            "qr_hash": result.get("qr_hash") or "",
            "started_at": started_at,
            "finished_at": finished_at,
            "metadata_json": self._metadata_json(result),
        }

    def _find_existing(self, document, result):
        domain = [
            ("document_id", "=", document.id),
            ("transmission_type", "=", self.TRANSMISSION_TYPE),
        ]
        request_hash = result.get("request_hash")
        if request_hash:
            domain.append(("request_hash", "=", request_hash))
        else:
            domain.extend([
                ("country_identifier", "=", result.get("cdc") or document.country_identifier or ""),
                ("signed_xml_sha256", "=", result.get("signed_xml_sha256") or ""),
                ("qr_hash", "=", result.get("qr_hash") or ""),
                ("error_code", "=", result.get("failed_stage") or ""),
            ])
        return self.env["fiscal.transmission"].sudo().search(domain, limit=1)

    def _next_attempt_number(self, document):
        attempts = document.transmission_ids.mapped("attempt_number")
        return max(attempts or [0]) + 1

    def _state_from_result(self, result):
        status = result.get("submission_status")
        if status == "accepted":
            return "accepted"
        if status == "rejected":
            return "rejected"
        if result.get("failed_stage") in (
            "test_submission",
            "production_submission",
        ):
            return "failed_retryable"
        if result.get("failed_stage"):
            return "failed_final"
        return "failed_final"

    def _metadata_json(self, result):
        metadata = {
            "service": "py_sifen_transmission_persistence",
            "pipeline_failed_stage": result.get("failed_stage") or "",
            "submission_status": result.get("submission_status") or "",
            "retryable": bool(result.get("retryable")),
            "retry_category": result.get("retry_category") or "",
        }
        return json.dumps(
            metadata,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
