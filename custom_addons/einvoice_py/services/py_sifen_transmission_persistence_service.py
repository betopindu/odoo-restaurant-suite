import json
from urllib.parse import urlsplit, urlunsplit

from psycopg2 import errors

from odoo import fields
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
    PySifenCredentialProvider,
)
from odoo.addons.einvoice_py.services.py_sifen_submission_pipeline_service import (
    PySifenSubmissionPipelineService,
)
from odoo.addons.einvoice_py.services.py_sifen_authority_incident_service import (
    PySifenAuthorityIncidentService,
)
from odoo.addons.einvoice_py.services.py_source_artifact_service import (
    PySourceArtifactService,
)


class PySifenTransmissionPersistenceService:
    """Persist SIFEN submission pipeline results without storing secrets."""

    TRANSMISSION_TYPE = "submit"

    def __init__(
        self,
        env,
        submission_pipeline_service=None,
        credential_provider=None,
        source_artifact_service=None,
    ):
        self.env = env
        self.submission_pipeline_service = (
            submission_pipeline_service or PySifenSubmissionPipelineService(env)
        )
        self.credential_provider = (
            credential_provider or PySifenCredentialProvider(env)
        )
        self.source_artifact_service = (
            source_artifact_service or PySourceArtifactService(env)
        )

    def submit_and_persist(self, **kwargs):
        document = kwargs.get("document")
        if not document:
            raise ValidationError("SIFEN transmission persistence requires a document.")
        document.ensure_one()
        self._validate_document(document)
        self._lock_document(document)
        self._validate_not_accepted(document)
        self._validate_no_ambiguous_submission(document)
        submission_kwargs = self._submission_kwargs(
            document=document,
            kwargs=kwargs,
        )
        self._persist_retry_payload(document, submission_kwargs.get("payload"))
        started_at = fields.Datetime.now()
        transmission = self._create_pending_transmission(
            document=document,
            started_at=started_at,
        )
        document.with_context(einvoice_skip_fiscal_document_lock=True).write({
            "state": "submitted",
            "submitted_at": started_at,
        })
        result = self._submit_for_environment(
            document=document,
            kwargs=submission_kwargs,
        )
        self._validate_result(result)
        finished_at = fields.Datetime.now()
        transmission.write(self._transmission_values(
            document=document,
            result=result,
            started_at=started_at,
            finished_at=finished_at,
        ))
        self._persist_normalized_response(document, transmission, result)
        self._update_document_from_result(document, result)
        return {
            "result": result,
            "transmission_id": transmission.id,
        }

    def _lock_document(self, document):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    """
                    SELECT id
                      FROM fiscal_document
                     WHERE id = %s
                     FOR UPDATE NOWAIT
                    """,
                    [document.id],
                )
                locked_id = self.env.cr.fetchone()
        except errors.LockNotAvailable:
            raise ValidationError(
                "SIFEN submission is already in progress for this document."
            ) from None
        if not locked_id:
            raise ValidationError("SIFEN submission document no longer exists.")

    def _validate_not_accepted(self, document):
        if document.state == "accepted":
            raise ValidationError(
                "An accepted fiscal document cannot be submitted again."
            )
        if self.env["fiscal.transmission"].sudo().search_count([
            ("document_id", "=", document.id),
            ("transmission_type", "=", self.TRANSMISSION_TYPE),
            ("state", "=", "accepted"),
        ]):
            raise ValidationError(
                "A fiscal document with an accepted transmission cannot be submitted again."
            )

    def _validate_no_ambiguous_submission(self, document):
        cdc = (document.country_identifier or document.py_cdc or "").strip()
        if not cdc:
            return
        transmission_model = self.env["fiscal.transmission"].sudo()
        if transmission_model.search_count([
            ("transmission_type", "=", self.TRANSMISSION_TYPE),
            ("country_code", "=", "PY"),
            ("environment", "=", "test"),
            ("tenant_id", "=", document.tenant_id.id),
            ("company_id", "=", document.company_id.id),
            ("country_identifier", "=", cdc),
            "|", ("state", "=", "sent"),
            ("error_code", "=", "ambiguous_submission"),
        ]) or transmission_model.search_count([
            ("transmission_type", "=", "status_query"),
            ("country_code", "=", "PY"),
            ("environment", "=", "test"),
            ("tenant_id", "=", document.tenant_id.id),
            ("company_id", "=", document.company_id.id),
            ("country_identifier", "=", cdc),
            ("error_code", "=", "reconciliation_not_found"),
        ]):
            raise ValidationError(
                "SIFEN submission status is ambiguous; Consulta DE reconciliation is required."
            )

    def _persist_retry_payload(self, document, payload):
        if not isinstance(payload, dict):
            raise ValidationError(
                "SIFEN submission requires a dictionary payload."
            )
        return self.source_artifact_service.persist_payload(
            document=document,
            payload=payload,
        )

    def _create_pending_transmission(self, *, document, started_at):
        return self.env["fiscal.transmission"].sudo().create({
            "document_id": document.id,
            "transmission_type": self.TRANSMISSION_TYPE,
            "state": "pending",
            "country_code": (document.country_code or "").upper(),
            "environment": document.environment,
            "country_identifier": (
                document.country_identifier or document.py_cdc or ""
            ),
            "attempt_number": self._next_attempt_number(document),
            "started_at": started_at,
            "metadata_json": json.dumps(
                {
                    "service": "py_sifen_transmission_persistence",
                    "submission_status": "pending",
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        })

    def _update_document_from_result(self, document, result):
        state = self._state_from_result(result)
        values = {
            "state": state,
            "authority_status": result.get("authority_code") or "",
            "authority_receipt_ref": (
                result.get("authority_receipt_ref") or ""
            ),
        }
        if state == "accepted":
            values["accepted_at"] = fields.Datetime.now()
        elif state == "rejected":
            values["rejected_at"] = fields.Datetime.now()
        document.with_context(einvoice_skip_fiscal_document_lock=True).write(
            values
        )

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
            self._persist_normalized_response(document, transmission, result)
            return transmission
        values["attempt_number"] = self._next_attempt_number(document)
        transmission = self.env["fiscal.transmission"].sudo().create(values)
        self._persist_normalized_response(document, transmission, result)
        return transmission

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

    def _submission_kwargs(self, *, document, kwargs):
        if kwargs.get("credentials") is not None:
            return kwargs
        explicit_inputs = (
            kwargs.get("certificate_bytes"),
            kwargs.get("private_key_bytes"),
            kwargs.get("private_key_password"),
            kwargs.get("endpoint_url"),
            kwargs.get("mutual_tls_credential"),
            kwargs.get("timeout_seconds"),
        )
        if any(value is not None and value is not False for value in explicit_inputs):
            return kwargs
        submission_kwargs = dict(kwargs)
        submission_kwargs["credentials"] = self.credential_provider.resolve(
            document=document,
        )
        return submission_kwargs

    def _validate_result(self, result):
        if not isinstance(result, dict):
            raise ValidationError("SIFEN transmission persistence result must be a dictionary.")
        if not result.get("failed_stage") and not result.get("submission_status"):
            raise ValidationError(
                "SIFEN transmission persistence result must include a pipeline outcome."
            )

    def _transmission_values(self, *, document, result, started_at, finished_at):
        ambiguous = bool(result.get("ambiguous"))
        return {
            "document_id": document.id,
            "transmission_type": self.TRANSMISSION_TYPE,
            "state": self._state_from_result(result),
            "country_code": (document.country_code or "").upper(),
            "environment": document.environment,
            "country_identifier": result.get("cdc") or document.country_identifier or "",
            "request_hash": result.get("request_hash") or "",
            "response_hash": result.get("response_hash") or "",
            "endpoint_url": self._safe_endpoint(result.get("endpoint_url")),
            "http_status": int(result.get("http_status") or 0),
            "duration_ms": max(0, int(result.get("duration_ms") or 0)),
            "authority_status_code": result.get("authority_code") or "",
            "authority_message": result.get("authority_message") or "",
            "error_code": (
                "ambiguous_submission"
                if ambiguous
                else result.get("failed_stage") or ""
            ),
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
        if result.get("ambiguous"):
            return "manual_review"
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
        incident = PySifenAuthorityIncidentService().classify(
            authority_code=result.get("authority_code"),
            authority_message=result.get("authority_message"),
        )
        metadata = {
            "service": "py_sifen_transmission_persistence",
            "pipeline_failed_stage": result.get("failed_stage") or "",
            "submission_status": result.get("submission_status") or "",
            "retryable": bool(result.get("retryable")),
            "retry_category": result.get("retry_category") or "",
            "ambiguous": bool(result.get("ambiguous")),
            "resolution_status": (
                "remote_query_required"
                if result.get("ambiguous")
                else ""
            ),
            "authority_receipt_ref": (
                result.get("authority_receipt_ref") or ""
            ),
            "authority_incident_type": incident.incident_type,
            "manual_retry_allowed": incident.manual_retry_allowed,
            "automatic_retry_allowed": incident.automatic_retry_allowed,
        }
        return json.dumps(
            metadata,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _safe_endpoint(self, value):
        parsed = urlsplit(str(value or ""))
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            return ""
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    def _persist_normalized_response(self, document, transmission, result):
        if not result.get("response_hash") and not result.get("authority_code"):
            return False
        existing = self.env["fiscal.attachment"].sudo().search([
            ("transmission_id", "=", transmission.id),
            ("attachment_type", "=", "authority_response"),
        ], limit=1)
        if existing:
            return existing
        incident = PySifenAuthorityIncidentService().classify(
            authority_code=result.get("authority_code"),
            authority_message=result.get("authority_message"),
        )
        payload = {
            "schema_version": 1,
            "submission_status": result.get("submission_status") or "",
            "authority_code": result.get("authority_code") or "",
            "authority_message": result.get("authority_message") or "",
            "authority_receipt_ref": result.get("authority_receipt_ref") or "",
            "http_status": int(result.get("http_status") or 0),
            "duration_ms": max(0, int(result.get("duration_ms") or 0)),
            "request_hash": result.get("request_hash") or "",
            "response_hash": result.get("response_hash") or "",
            "response_category": result.get("response_category") or "",
            "ambiguous": bool(result.get("ambiguous")),
            "authority_incident_type": incident.incident_type,
            "manual_retry_allowed": incident.manual_retry_allowed,
            "automatic_retry_allowed": incident.automatic_retry_allowed,
        }
        return self.env["fiscal.attachment"].sudo().create_json_payload_attachment(
            document,
            "authority_response",
            f"{document.uuid}-sifen-response-{transmission.id}.json",
            payload,
            transmission=transmission,
        )
