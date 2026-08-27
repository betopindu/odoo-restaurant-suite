import base64
import hashlib
import re

from lxml import etree

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_qr_generation_service import (
    PyQrGenerationService,
)
from odoo.addons.einvoice_py.services.py_final_rde_attachment_service import (
    PyFinalRdeAttachmentService,
)
from odoo.addons.einvoice_py.services.py_qr_payload_attachment_service import (
    PyQrPayloadAttachmentService,
)
from odoo.addons.einvoice_py.services.py_sifen_sandbox_transport import (
    PySifenSandboxTransport,
)
from odoo.addons.einvoice_py.services.py_sifen_rde_assembler import (
    PySifenRdeAssembler,
)
from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
    PySifenRuntimeCredentials,
)
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenSubmissionService,
)
from odoo.addons.einvoice_py.services.py_signing_pipeline_service import (
    PySigningPipelineService,
)
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)
from odoo.addons.einvoice_py.services.py_xsd_validation_service import (
    PyXsdValidationService,
)


class PySifenSubmissionPipelineService:
    """Orchestrate Paraguay test submission without duplicating stage logic."""

    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS

    def __init__(
        self,
        env,
        *,
        signing_pipeline_service=None,
        qr_generation_service=None,
        qr_payload_attachment_service=None,
        xsd_validation_service=None,
        rde_assembler=None,
        submission_service=None,
        transport=None,
        final_rde_attachment_service=None,
    ):
        self.env = env
        self.signing_pipeline_service = signing_pipeline_service or PySigningPipelineService(env)
        self.qr_generation_service = qr_generation_service or PyQrGenerationService()
        self.qr_payload_attachment_service = (
            qr_payload_attachment_service
            if qr_payload_attachment_service is not None
            else PyQrPayloadAttachmentService(env)
        )
        self.xsd_validation_service = xsd_validation_service or PyXsdValidationService()
        self.rde_assembler = (
            rde_assembler
            if rde_assembler is not None
            else PySifenRdeAssembler(
                xsd_validation_service=self.xsd_validation_service
            )
        )
        self.final_rde_attachment_service = (
            final_rde_attachment_service
            if final_rde_attachment_service is not None
            else PyFinalRdeAttachmentService(env)
        )
        self.submission_service = submission_service or PySifenSubmissionService(
            xsd_validation_service=self.xsd_validation_service,
            transport=transport or PySifenSandboxTransport(env),
        )

    def submit(self, **kwargs):
        return self._submit(expected_environment=None, **kwargs)

    def submit_test(self, **kwargs):
        return self._submit(expected_environment="test", **kwargs)

    def submit_production(self, **kwargs):
        return self._submit(expected_environment="production", **kwargs)

    def _submit(
        self,
        *,
        expected_environment,
        document,
        payload,
        signing_timestamp,
        certificate_bytes=None,
        private_key_bytes=None,
        endpoint_url=None,
        mutual_tls_credential=None,
        private_key_password=None,
        soap_action=None,
        timeout_seconds=None,
        filename=None,
        credentials=None,
        pre_post_callback=None,
    ):
        document.ensure_one()
        self._validate_environment(document, expected_environment)
        (
            certificate_bytes,
            private_key_bytes,
            private_key_password,
            endpoint_url,
            mutual_tls_credential,
            timeout_seconds,
        ) = self._credential_inputs(
            credentials=credentials,
            certificate_bytes=certificate_bytes,
            private_key_bytes=private_key_bytes,
            private_key_password=private_key_password,
            endpoint_url=endpoint_url,
            mutual_tls_credential=mutual_tls_credential,
            timeout_seconds=timeout_seconds,
        )
        result = self._base_result()

        signing_result = self._run_stage(
            result,
            "signing",
            lambda: self.signing_pipeline_service.sign(
                document=document,
                payload=payload,
                certificate_bytes=certificate_bytes,
                private_key_bytes=private_key_bytes,
                private_key_password=private_key_password,
                signing_timestamp=signing_timestamp,
                filename=filename,
            ),
        )
        if signing_result is None:
            return result
        self._merge_signing_result(result, signing_result)

        signed_xml_bytes = self._run_stage(
            result,
            "signed_xml_attachment",
            lambda: self._signed_xml_bytes(signing_result),
        )
        if signed_xml_bytes is None:
            return result
        result["signed_xml_sha256"] = hashlib.sha256(signed_xml_bytes).hexdigest()

        qr_result = self._run_stage(
            result,
            "qr_generation",
            lambda: self.qr_generation_service.generate(
                document=document,
                signed_xml_bytes=signed_xml_bytes,
                digest_value=signing_result.get("digest_value"),
                cdc=signing_result.get("cdc"),
            ),
        )
        if qr_result is None:
            return result
        result["qr_hash"] = qr_result.get("qr_hash", "")
        result["qr_payload"] = qr_result.get("qr_string", "")
        qr_attachment = self._run_stage(
            result,
            "qr_persistence",
            lambda: self.qr_payload_attachment_service.persist(
                document=document,
                qr_payload=result["qr_payload"],
                qr_hash=result["qr_hash"],
                signed_attachment_id=signing_result.get("signed_attachment_id"),
                signed_xml_sha256=result["signed_xml_sha256"],
                digest_value=signing_result.get("digest_value"),
            ),
        )
        if qr_attachment is None:
            return result

        assembly_result = self._run_stage(
            result,
            "final_xml_preparation",
            lambda: self.rde_assembler.assemble(
                signed_xml_bytes=signed_xml_bytes,
                gcamfufd_xml_bytes=self._qr_group_xml(
                    qr_result,
                    result["qr_payload"],
                ),
                cdc=result["cdc"],
                qr_url=result["qr_payload"],
            ),
        )
        if assembly_result is None:
            return result
        final_xml_bytes = assembly_result.final_xml_bytes

        if not assembly_result.xsd_valid:
            self._fail(
                result,
                "final_xsd_validation",
                "Final signed Paraguay XML failed local SIFEN XSD validation.",
                xsd_report={
                    "errors": [
                        {
                            "failing_element": error.element,
                            "path": error.path,
                            "line": error.line,
                            "column": error.column,
                            "message": error.message,
                        }
                        for error in assembly_result.validation_errors
                    ],
                },
            )
            result.update(
                self._safe_xsd_diagnostic(assembly_result.validation_errors)
            )
            return result

        final_attachment = self._run_stage(
            result,
            "final_xml_persistence",
            lambda: self.final_rde_attachment_service.persist(
                document=document,
                final_xml_bytes=final_xml_bytes,
                cdc=result["cdc"],
                signed_attachment_id=signing_result.get("signed_attachment_id"),
                signed_xml_sha256=result["signed_xml_sha256"],
                qr_attachment_id=qr_attachment.id,
                qr_sha256=qr_attachment.sha256,
            ),
        )
        if final_attachment is None:
            return result
        result["final_xml_attachment_id"] = final_attachment.id

        def before_post(request_evidence):
            if pre_post_callback is None:
                return
            pre_post_callback(dict(request_evidence, **{
                "payload_attachment_id": signing_result.get("payload_attachment_id"),
                "payload_sha256": signing_result.get("payload_sha256"),
                "unsigned_xml_attachment_id": signing_result.get("unsigned_attachment_id"),
                "unsigned_xml_sha256": signing_result.get("unsigned_sha256"),
                "signed_xml_attachment_id": signing_result.get("signed_attachment_id"),
                "signed_xml_sha256": result["signed_xml_sha256"],
                "qr_attachment_id": qr_attachment.id,
                "qr_sha256": qr_attachment.sha256,
                "qr_hash": result["qr_hash"],
                "rde_attachment_id": final_attachment.id,
                "rde_sha256": final_attachment.sha256,
                "signing_time": signing_result.get("signing_time"),
                "digest_value": signing_result.get("digest_value"),
            }))

        submission_result = self._run_stage(
            result,
            self._submission_stage(document.environment),
            lambda: self.submission_service.submit_final_xml(
                document=document,
                final_xml_bytes=final_xml_bytes,
                endpoint_url=endpoint_url,
                soap_action=soap_action,
                timeout_seconds=timeout_seconds,
                mutual_tls_credential=mutual_tls_credential,
                before_post=before_post,
            ),
        )
        if submission_result is None:
            return result
        self._merge_submission_result(result, submission_result)
        result["ok"] = submission_result.get("outcome") == "accepted"
        result["failed_stage"] = (
            "" if result["ok"] else self._submission_stage(document.environment)
        )
        result["error_message"] = (
            ""
            if result["ok"]
            else f"SIFEN {document.environment} submission was not accepted."
        )
        return result

    def _validate_environment(self, document, expected_environment):
        if document.environment not in ("test", "production"):
            raise ValidationError("Paraguay SIFEN submission environment is unsupported.")
        if expected_environment and document.environment != expected_environment:
            raise ValidationError(
                f"Paraguay SIFEN {expected_environment} submission requires a "
                f"{expected_environment} environment document."
            )

    def _submission_stage(self, environment):
        return f"{environment}_submission"

    def _credential_inputs(
        self,
        *,
        credentials,
        certificate_bytes,
        private_key_bytes,
        private_key_password,
        endpoint_url,
        mutual_tls_credential,
        timeout_seconds,
    ):
        explicit_inputs = (
            certificate_bytes,
            private_key_bytes,
            private_key_password,
            endpoint_url,
            mutual_tls_credential,
            timeout_seconds,
        )
        if credentials is None:
            return explicit_inputs
        if not isinstance(credentials, PySifenRuntimeCredentials):
            raise ValidationError(
                "Paraguay SIFEN runtime credentials are invalid."
            )
        if any(value is not None and value is not False for value in explicit_inputs):
            raise ValidationError(
                "Paraguay SIFEN runtime credentials cannot be mixed with explicit credential inputs."
            )
        return (
            credentials.signing_certificate_bytes,
            credentials.signing_private_key_bytes,
            credentials.signing_private_key_password,
            credentials.endpoint_url,
            credentials.mutual_tls_credential,
            credentials.timeout_seconds,
        )

    def _base_result(self):
        return {
            "ok": False,
            "failed_stage": "",
            "error_message": "",
            "cdc": "",
            "signed_xml_sha256": "",
            "digest_value": "",
            "certificate_fingerprint_sha256": "",
            "qr_hash": "",
            "qr_payload": "",
            "submission_status": "",
            "authority_code": "",
            "authority_message": "",
            "authority_receipt_ref": "",
            "request_hash": "",
            "response_hash": "",
            "retryable": False,
            "retry_category": "",
            "ambiguous": False,
            "endpoint_url": "",
            "http_status": 0,
            "duration_ms": 0,
            "response_category": "",
            "diagnostic_code": "",
            "diagnostic_detail": "",
            "final_xml_attachment_id": 0,
        }

    def _run_stage(self, result, stage, operation):
        try:
            return operation()
        except ValidationError as error:
            self._fail(result, stage, self._stage_failure_message(stage))
            result.update(self._safe_validation_diagnostic(stage, error))
            return None

    def _safe_validation_diagnostic(self, stage, error):
        """Return allow-listed technical evidence without fiscal/secret data."""
        message = str(error or "")
        schema_prefix = (
            "Cannot build Paraguay unsigned XML; payload is not schema-ready: "
        )
        if stage == "signing" and message.startswith(schema_prefix):
            labels = [
                label.strip()
                for label in message[len(schema_prefix):].split(";")
            ]
            if labels and all(
                label and re.fullmatch(r"[A-Za-z0-9 ()_-]{1,80}", label)
                for label in labels
            ):
                return {
                    "diagnostic_code": "payload_schema_not_ready",
                    "diagnostic_detail": "; ".join(labels)[:500],
                }
        return {
            "diagnostic_code": f"{stage}_validation_failed",
            "diagnostic_detail": "",
        }

    def _safe_xsd_diagnostic(self, errors):
        """Allow-list structural XSD evidence without persisting XML values."""
        error = next(iter(errors or ()), None)
        if error is None:
            return {
                "diagnostic_code": "final_xsd_validation_failed",
                "diagnostic_detail": "",
            }
        element = re.sub(r"[^A-Za-z0-9_.:-]", "", error.element or "")[:80]
        message = error.message or ""
        category = "schema_validation"
        if "[facet 'pattern']" in message:
            category = "facet_pattern"
        elif "Missing child element" in message:
            category = "missing_child"
        elif "This element is not expected" in message:
            category = "unexpected_element"
        parts = [f"category={category}"]
        if element:
            parts.insert(0, f"element={element}")
        if isinstance(error.line, int) and error.line >= 0:
            parts.append(f"line={error.line}")
        if isinstance(error.column, int) and error.column >= 0:
            parts.append(f"column={error.column}")
        return {
            "diagnostic_code": "final_xsd_structure_invalid",
            "diagnostic_detail": "; ".join(parts)[:500],
        }

    def _fail(self, result, stage, message, xsd_report=None):
        result["ok"] = False
        result["failed_stage"] = stage
        result["error_message"] = message
        if xsd_report is not None:
            result["xsd_errors"] = [
                {
                    "failing_element": error.get("failing_element"),
                    "path": error.get("path"),
                    "line": error.get("line"),
                    "column": error.get("column"),
                    "message": error.get("message", ""),
                }
                for error in xsd_report.get("errors", [])
            ]
        return result

    def _stage_failure_message(self, stage):
        messages = {
            "signing": "Paraguay signing pipeline failed.",
            "signed_xml_attachment": "Signed Paraguay XML attachment could not be read.",
            "qr_generation": "Paraguay QR generation failed.",
            "qr_persistence": "Paraguay QR payload could not be persisted.",
            "final_xml_preparation": "Final signed Paraguay XML with QR could not be prepared.",
            "final_xsd_validation": "Final signed Paraguay XML failed local SIFEN XSD validation.",
            "final_xml_persistence": "Final signed Paraguay rDE could not be persisted.",
            "test_submission": "SIFEN test submission failed.",
            "production_submission": "SIFEN production submission failed.",
        }
        return messages.get(stage, "Paraguay SIFEN submission pipeline failed.")

    def _merge_signing_result(self, result, signing_result):
        result["cdc"] = signing_result.get("cdc", "")
        result["digest_value"] = signing_result.get("digest_value", "")
        result["certificate_fingerprint_sha256"] = signing_result.get(
            "certificate_fingerprint_sha256", ""
        )

    def _merge_submission_result(self, result, submission_result):
        result["submission_status"] = submission_result.get("outcome", "")
        result["authority_code"] = submission_result.get("authority_status_code", "")
        result["authority_message"] = submission_result.get("authority_message", "")
        result["authority_receipt_ref"] = submission_result.get(
            "authority_receipt_ref",
            "",
        )
        result["request_hash"] = submission_result.get("request_hash", "")
        result["response_hash"] = submission_result.get("response_hash", "")
        result["retryable"] = bool(submission_result.get("retryable"))
        result["ambiguous"] = bool(submission_result.get("ambiguous"))
        metadata = submission_result.get("metadata_json") or {}
        result["endpoint_url"] = submission_result.get("endpoint_url") or ""
        result["http_status"] = int(submission_result.get("http_status") or 0)
        result["duration_ms"] = max(0, int(submission_result.get("duration_ms") or 0))
        result["response_category"] = metadata.get("response_category", "")
        result["retry_category"] = metadata.get("transport_error_category", "")
        if (
            not result["retry_category"]
            and result["retryable"]
            and metadata.get("response_category") == "http_failure"
        ):
            result["retry_category"] = "http_failure"

    def _signed_xml_bytes(self, signing_result):
        if signing_result.get("signed_xml_bytes"):
            signed_xml_bytes = signing_result["signed_xml_bytes"]
            return signed_xml_bytes.encode("utf-8") if isinstance(signed_xml_bytes, str) else signed_xml_bytes
        attachment_id = signing_result.get("signed_attachment_id")
        attachment = self.env["fiscal.attachment"].sudo().browse(attachment_id).exists()
        if not attachment or not attachment.ir_attachment_id:
            raise ValidationError("Signed Paraguay XML attachment is missing.")
        return base64.b64decode(attachment.ir_attachment_id.datas or b"")

    def _qr_group_xml(self, qr_result, qr_payload):
        qr_group_xml = qr_result.get("gcamfufd_xml_bytes")
        if qr_group_xml:
            return qr_group_xml
        qr_group = etree.Element(f"{{{self.SIFEN_NS}}}gCamFuFD")
        etree.SubElement(
            qr_group,
            f"{{{self.SIFEN_NS}}}dCarQR",
        ).text = qr_payload
        return etree.tostring(qr_group, encoding="UTF-8")
