import base64
import hashlib

from lxml import etree

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_qr_generation_service import (
    PyQrGenerationService,
)
from odoo.addons.einvoice_py.services.py_sifen_sandbox_transport import (
    PySifenSandboxTransport,
)
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenTestSubmissionService,
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
        xsd_validation_service=None,
        submission_service=None,
        transport=None,
    ):
        self.env = env
        self.signing_pipeline_service = signing_pipeline_service or PySigningPipelineService(env)
        self.qr_generation_service = qr_generation_service or PyQrGenerationService()
        self.xsd_validation_service = xsd_validation_service or PyXsdValidationService()
        self.submission_service = submission_service or PySifenTestSubmissionService(
            xsd_validation_service=self.xsd_validation_service,
            transport=transport or PySifenSandboxTransport(env),
        )

    def submit_test(
        self,
        *,
        document,
        payload,
        certificate_bytes,
        private_key_bytes,
        signing_timestamp,
        endpoint_url,
        mutual_tls_credential=None,
        private_key_password=None,
        soap_action=None,
        timeout_seconds=None,
        filename=None,
    ):
        document.ensure_one()
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

        final_xml_bytes = self._run_stage(
            result,
            "final_xml_preparation",
            lambda: self._final_xml_with_qr(
                signed_xml_bytes=signed_xml_bytes,
                qr_payload=result["qr_payload"],
            ),
        )
        if final_xml_bytes is None:
            return result

        xsd_report = self._run_stage(
            result,
            "final_xsd_validation",
            lambda: self.xsd_validation_service.validate_final_signed_xml(final_xml_bytes),
        )
        if xsd_report is None:
            return result
        if not xsd_report.get("valid"):
            return self._fail(
                result,
                "final_xsd_validation",
                "Final signed Paraguay XML failed local SIFEN XSD validation.",
                xsd_report=xsd_report,
            )

        submission_result = self._run_stage(
            result,
            "test_submission",
            lambda: self.submission_service.submit_final_xml(
                document=document,
                final_xml_bytes=final_xml_bytes,
                endpoint_url=endpoint_url,
                soap_action=soap_action,
                timeout_seconds=timeout_seconds,
                mutual_tls_credential=mutual_tls_credential,
            ),
        )
        if submission_result is None:
            return result
        self._merge_submission_result(result, submission_result)
        result["ok"] = submission_result.get("outcome") == "accepted"
        result["failed_stage"] = "" if result["ok"] else "test_submission"
        result["error_message"] = "" if result["ok"] else "SIFEN test submission was not accepted."
        return result

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
            "request_hash": "",
            "response_hash": "",
        }

    def _run_stage(self, result, stage, operation):
        try:
            return operation()
        except ValidationError:
            self._fail(result, stage, self._stage_failure_message(stage))
            return None

    def _fail(self, result, stage, message, xsd_report=None):
        result["ok"] = False
        result["failed_stage"] = stage
        result["error_message"] = message
        if xsd_report is not None:
            result["xsd_errors"] = [
                {
                    "failing_element": error.get("failing_element"),
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
            "final_xml_preparation": "Final signed Paraguay XML with QR could not be prepared.",
            "final_xsd_validation": "Final signed Paraguay XML failed local SIFEN XSD validation.",
            "test_submission": "SIFEN test submission failed.",
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
        result["request_hash"] = submission_result.get("request_hash", "")
        result["response_hash"] = submission_result.get("response_hash", "")

    def _signed_xml_bytes(self, signing_result):
        if signing_result.get("signed_xml_bytes"):
            signed_xml_bytes = signing_result["signed_xml_bytes"]
            return signed_xml_bytes.encode("utf-8") if isinstance(signed_xml_bytes, str) else signed_xml_bytes
        attachment_id = signing_result.get("signed_attachment_id")
        attachment = self.env["fiscal.attachment"].sudo().browse(attachment_id).exists()
        if not attachment or not attachment.ir_attachment_id:
            raise ValidationError("Signed Paraguay XML attachment is missing.")
        return base64.b64decode(attachment.ir_attachment_id.datas or b"")

    def _final_xml_with_qr(self, *, signed_xml_bytes, qr_payload):
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
        root = etree.fromstring(signed_xml_bytes, parser)
        existing = root.findall(f"{{{self.SIFEN_NS}}}gCamFuFD")
        if existing:
            raise ValidationError("Final signed Paraguay XML already contains QR content.")
        qr_group = etree.SubElement(root, f"{{{self.SIFEN_NS}}}gCamFuFD")
        etree.SubElement(qr_group, f"{{{self.SIFEN_NS}}}dCarQR").text = qr_payload
        etree.indent(root, space="  ")
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)
