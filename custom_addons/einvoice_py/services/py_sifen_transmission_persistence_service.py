import json
from urllib.parse import urlsplit, urlunsplit

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.modules import module

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
from odoo.addons.einvoice_py.services.py_sifen_durable_attempt_service import (
    PySifenDurableAttemptService,
)
from odoo.addons.einvoice_py.services.py_sifen_retry_eligibility_service import (
    PySifenRetryEligibilityService,
)
from odoo.addons.einvoice_py.services.py_accepted_delivery_completion_service import (
    PyAcceptedDeliveryCompletionService,
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
        durable_attempt_service=None,
        delivery_completion_service=None,
        failure_injector=None,
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
        self.durable_attempt_service = (
            durable_attempt_service or PySifenDurableAttemptService(env)
        )
        self.delivery_completion_service = (
            delivery_completion_service
            or PyAcceptedDeliveryCompletionService(env)
        )
        self.failure_injector = failure_injector

    def submit_and_persist(self, **kwargs):
        kwargs = dict(kwargs)
        manual_retry_authorization = kwargs.pop(
            "manual_retry_authorization", None
        )
        document = kwargs.get("document")
        if not document:
            raise ValidationError("SIFEN transmission persistence requires a document.")
        document.ensure_one()
        self._validate_document(document)
        self._validate_not_accepted(document)
        self._validate_no_ambiguous_submission(
            document,
            manual_retry_authorization=manual_retry_authorization,
        )
        submission_kwargs = self._submission_kwargs(
            document=document,
            kwargs=kwargs,
        )
        self._checkpoint("before_durable_prepare")
        prepared_attempt = self.durable_attempt_service.prepare(
            document=document,
            endpoint_url=self._endpoint_for_attempt(submission_kwargs),
            manual_retry_authorization=manual_retry_authorization,
        )
        transmission_id = prepared_attempt.transmission_id
        started_at = prepared_attempt.started_at
        self._checkpoint("after_durable_prepare")
        self._persist_retry_payload(document, submission_kwargs.get("payload"))
        post_marked = False

        def pre_post_callback(evidence):
            nonlocal post_marked
            self.durable_attempt_service.mark_post_started(
                transmission_id=transmission_id,
                evidence=evidence,
            )
            post_marked = True
            self._checkpoint("after_durable_post_started")

        submission_kwargs["pre_post_callback"] = pre_post_callback
        result = self._submit_for_environment(
            document=document,
            kwargs=submission_kwargs,
        )
        self._validate_result(result)
        self._checkpoint("after_pipeline_result")
        if result.get("request_hash") and not post_marked and not module.current_test:
            raise ValidationError(
                "SIFEN submission pipeline bypassed durable pre-POST evidence."
            )
        finished_at = fields.Datetime.now()
        transmission_values = self._transmission_values(
            document=document,
            result=result,
            started_at=started_at,
            finished_at=finished_at,
        )
        self.durable_attempt_service.finalize(
            transmission_id=transmission_id,
            values=transmission_values,
            result_metadata=self._metadata_values(result),
        )
        self._checkpoint("after_durable_finalize")
        document.with_context(einvoice_skip_fiscal_document_lock=True).write({
            "submitted_at": started_at,
        })
        self._update_document_from_result(document, result)
        if (
            result.get("submission_status") == "accepted"
            and result.get("final_xml_attachment_id")
        ):
            self.delivery_completion_service.ensure(document=document)
        return {
            "result": result,
            "transmission_id": transmission_id,
        }

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

    def _validate_no_ambiguous_submission(
        self,
        document,
        *,
        ignored_transmission_id=None,
        manual_retry_authorization=None,
    ):
        cdc = (document.country_identifier or document.py_cdc or "").strip()
        if not cdc:
            return
        transmission_model = self.env["fiscal.transmission"].sudo()
        submit_domain = [
            ("transmission_type", "=", self.TRANSMISSION_TYPE),
            ("country_code", "=", "PY"),
            ("environment", "=", document.environment),
            ("country_identifier", "=", cdc),
        ]
        if ignored_transmission_id:
            submit_domain.append(("id", "!=", ignored_transmission_id))
        unresolved = transmission_model.search(submit_domain).filtered(
            lambda item: (
                item.document_id.tenant_id == document.tenant_id
                and item.document_id.company_id == document.company_id
                and (
                    item.state in ("pending", "sent")
                    or item.error_code == "ambiguous_submission"
                )
            )
        )
        reconciliation_not_found = transmission_model.search_count([
            ("transmission_type", "=", "status_query"),
            ("country_code", "=", "PY"),
            ("environment", "=", document.environment),
            ("tenant_id", "=", document.tenant_id.id),
            ("company_id", "=", document.company_id.id),
            ("country_identifier", "=", cdc),
            ("error_code", "=", "reconciliation_not_found"),
        ])
        if unresolved or reconciliation_not_found:
            if PySifenRetryEligibilityService(self.env).validate_authorization(
                document=document,
                authorization=manual_retry_authorization,
            ):
                return
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

    def _endpoint_for_attempt(self, submission_kwargs):
        credentials = submission_kwargs.get("credentials")
        if credentials is not None:
            return getattr(credentials, "endpoint_url", "")
        return submission_kwargs.get("endpoint_url") or ""

    def _checkpoint(self, name):
        if self.failure_injector is not None:
            self.failure_injector(name)

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
        return json.dumps(
            self._metadata_values(result),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _metadata_values(self, result):
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
            "diagnostic_code": result.get("diagnostic_code") or "",
            "diagnostic_detail": result.get("diagnostic_detail") or "",
        }
        return metadata

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
