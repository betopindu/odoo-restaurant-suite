import base64
import hashlib
import json
from datetime import datetime

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_submission_pipeline_service import (
    PySifenSubmissionPipelineService,
)
from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
    PySifenRuntimeCredentials,
)
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)


class _SigningPipelineStub:
    def __init__(self, attachment_id=None, error=None):
        self.attachment_id = attachment_id
        self.error = error
        self.calls = []

    def sign(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {
            "cdc": TestPySifenSubmissionPipelineService.CDC,
            "digest_value": TestPySifenSubmissionPipelineService.DIGEST_VALUE,
            "certificate_fingerprint_sha256": "a" * 64,
            "signed_attachment_id": self.attachment_id,
        }


class _QrGenerationStub:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {
            "qr_hash": "b" * 64,
            "qr_string": "https://example.test/qr?nVersion=150&cHashQR=" + ("b" * 64),
        }


class _XsdValidationStub:
    def __init__(self, valid=True):
        self.valid = valid
        self.calls = []

    def validate_final_signed_xml(self, xml_content):
        self.calls.append(xml_content)
        return {
            "valid": self.valid,
            "errors": [] if self.valid else [{"message": "fixture xsd error"}],
            "warnings": [],
        }


class _SubmissionStub:
    def __init__(self, error=None, outcome="accepted", result=None):
        self.error = error
        self.outcome = outcome
        self.result = result
        self.calls = []

    def submit_final_xml(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        if self.result is not None:
            return dict(self.result)
        return {
            "outcome": self.outcome,
            "authority_status_code": "0260" if self.outcome == "accepted" else "1300",
            "authority_message": "Aprobado" if self.outcome == "accepted" else "Rechazado",
            "request_hash": "c" * 64,
            "response_hash": "d" * 64,
        }


class TestPySifenSubmissionPipelineService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"
    DIGEST_VALUE = "digest-fixture"
    SIGNING_TIMESTAMP = datetime(2026, 7, 4, 12, 0, 0)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN Submission Pipeline Tenant",
            "code": "sifen-submission-pipeline",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "SIFEN Submission Pipeline Document",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Test Customer",
            "amount_total": 100,
            "idempotency_key": self.id(),
            "py_cdc": self.CDC,
            "py_cdc_dv": self.CDC[-1],
            "country_identifier": self.CDC,
        })
        self.signed_xml = self._signed_xml()
        self.signed_attachment = self._signed_attachment(self.signed_xml)
        self.signing = _SigningPipelineStub(attachment_id=self.signed_attachment.id)
        self.qr = _QrGenerationStub()
        self.xsd = _XsdValidationStub()
        self.submission = _SubmissionStub()

    def _service(self):
        return PySifenSubmissionPipelineService(
            self.env,
            signing_pipeline_service=self.signing,
            qr_generation_service=self.qr,
            xsd_validation_service=self.xsd,
            submission_service=self.submission,
        )

    def _submit(self):
        return self._service().submit_test(
            document=self.document,
            payload={"payload": "fixture"},
            certificate_bytes=b"certificate-secret-fixture",
            private_key_bytes=b"private-key-secret-fixture",
            private_key_password="password-secret-fixture",
            signing_timestamp=self.SIGNING_TIMESTAMP,
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=False,
        )

    def _signed_attachment(self, signed_xml):
        filename = f"{self.document.uuid}-signed.xml"
        ir_attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(signed_xml),
            "mimetype": "application/xml",
            "res_model": "fiscal.document",
            "res_id": self.document.id,
        })
        return self.env["fiscal.attachment"].sudo().create({
            "name": filename,
            "document_id": self.document.id,
            "attachment_type": "paraguay_xml_signed",
            "mimetype": "application/xml",
            "filename": filename,
            "ir_attachment_id": ir_attachment.id,
            "sha256": hashlib.sha256(signed_xml).hexdigest(),
            "is_sensitive": True,
        })

    def _signed_xml(self):
        namespace = PyUnsignedXmlBuilder.SIFEN_NS
        ds_namespace = "http://www.w3.org/2000/09/xmldsig#"
        root = etree.Element(f"{{{namespace}}}rDE", nsmap={None: namespace})
        etree.SubElement(root, f"{{{namespace}}}dVerFor").text = "150"
        de = etree.SubElement(root, f"{{{namespace}}}DE", {"Id": self.CDC})
        etree.SubElement(de, f"{{{namespace}}}dDVId").text = self.CDC[-1]
        etree.SubElement(de, f"{{{namespace}}}dFecFirma").text = "2026-07-04T12:00:00"
        etree.SubElement(de, f"{{{namespace}}}dSisFact").text = "1"
        signature = etree.SubElement(root, f"{{{ds_namespace}}}Signature")
        signed_info = etree.SubElement(signature, f"{{{ds_namespace}}}SignedInfo")
        reference = etree.SubElement(signed_info, f"{{{ds_namespace}}}Reference")
        etree.SubElement(reference, f"{{{ds_namespace}}}DigestValue").text = self.DIGEST_VALUE
        etree.indent(root, space="  ")
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    def test_successful_orchestration_returns_safe_normalized_result(self):
        result = self._submit()

        self.assertTrue(result["ok"])
        self.assertEqual(result["failed_stage"], "")
        self.assertEqual(result["cdc"], self.CDC)
        self.assertEqual(result["signed_xml_sha256"], hashlib.sha256(self.signed_xml).hexdigest())
        self.assertEqual(result["digest_value"], self.DIGEST_VALUE)
        self.assertEqual(result["certificate_fingerprint_sha256"], "a" * 64)
        self.assertEqual(result["qr_hash"], "b" * 64)
        self.assertTrue(result["qr_payload"].startswith("https://example.test/qr?"))
        self.assertEqual(result["submission_status"], "accepted")
        self.assertEqual(result["authority_code"], "0260")
        self.assertEqual(result["authority_message"], "Aprobado")
        self.assertEqual(result["request_hash"], "c" * 64)
        self.assertEqual(result["response_hash"], "d" * 64)
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("private-key-secret-fixture", serialized)
        self.assertNotIn("certificate-secret-fixture", serialized)
        self.assertNotIn("password-secret-fixture", serialized)

    def test_http_5xx_failure_has_scheduler_retry_category(self):
        self.submission.result = {
            "outcome": "transport_error",
            "authority_status_code": "",
            "authority_message": "SIFEN submission failed.",
            "authority_receipt_ref": "",
            "request_hash": "c" * 64,
            "response_hash": "d" * 64,
            "retryable": True,
            "metadata_json": {"response_category": "http_failure"},
        }

        result = self._submit()

        self.assertFalse(result["ok"])
        self.assertTrue(result["retryable"])
        self.assertEqual(result["retry_category"], "http_failure")

    def test_generic_submit_reuses_single_pipeline_execution(self):
        self.document.environment = "production"
        self.submission.outcome = "rejected"

        result = self._service().submit(
            document=self.document,
            payload={"payload": "fixture"},
            certificate_bytes=b"certificate-secret-fixture",
            private_key_bytes=b"private-key-secret-fixture",
            signing_timestamp=self.SIGNING_TIMESTAMP,
            endpoint_url="https://sifen-production.example.test/de",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_stage"], "production_submission")
        self.assertNotIn("test", result["error_message"].lower())
        self.assertNotIn("sandbox", result["error_message"].lower())
        self.assertEqual(len(self.signing.calls), 1)
        self.assertEqual(len(self.qr.calls), 1)
        self.assertEqual(len(self.xsd.calls), 1)
        self.assertEqual(len(self.submission.calls), 1)
        self.assertEqual(
            self.submission.calls[0]["endpoint_url"],
            "https://sifen-production.example.test/de",
        )

    def test_submit_production_delegates_to_single_pipeline_execution(self):
        self.document.environment = "production"

        result = self._service().submit_production(
            document=self.document,
            payload={"payload": "fixture"},
            certificate_bytes=b"certificate-secret-fixture",
            private_key_bytes=b"private-key-secret-fixture",
            signing_timestamp=self.SIGNING_TIMESTAMP,
            endpoint_url="https://sifen-production.example.test/de",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(len(self.signing.calls), 1)
        self.assertEqual(len(self.qr.calls), 1)
        self.assertEqual(len(self.xsd.calls), 1)
        self.assertEqual(len(self.submission.calls), 1)
        self.assertEqual(
            self.submission.calls[0]["endpoint_url"],
            "https://sifen-production.example.test/de",
        )

    def test_environment_specific_pipeline_methods_reject_wrong_environment(self):
        with self.assertRaisesRegex(ValidationError, "production environment"):
            self._service().submit_production(
                document=self.document,
                payload={"payload": "fixture"},
                signing_timestamp=self.SIGNING_TIMESTAMP,
            )

        self.document.environment = "production"
        with self.assertRaisesRegex(ValidationError, "test environment"):
            self._service().submit_test(
                document=self.document,
                payload={"payload": "fixture"},
                signing_timestamp=self.SIGNING_TIMESTAMP,
            )

        self.assertFalse(self.signing.calls)
        self.assertFalse(self.qr.calls)
        self.assertFalse(self.xsd.calls)
        self.assertFalse(self.submission.calls)

    def test_runtime_credentials_supply_pipeline_inputs(self):
        credentials = PySifenRuntimeCredentials(
            adapter_config=False,
            xml_signing_credential=False,
            mutual_tls_credential="mutual-tls-reference",
            signing_certificate_bytes=b"runtime-certificate",
            signing_private_key_bytes=b"runtime-private-key",
            signing_private_key_password=b"runtime-password",
            csc_id="0001",
            csc_value="runtime-csc",
            endpoint_url="https://sifen-test.example.test/de",
            timeout_seconds=17,
        )

        result = self._service().submit_test(
            document=self.document,
            payload={"payload": "fixture"},
            signing_timestamp=self.SIGNING_TIMESTAMP,
            credentials=credentials,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            self.signing.calls[0]["certificate_bytes"],
            b"runtime-certificate",
        )
        self.assertEqual(
            self.signing.calls[0]["private_key_bytes"],
            b"runtime-private-key",
        )
        self.assertEqual(
            self.submission.calls[0]["mutual_tls_credential"],
            "mutual-tls-reference",
        )
        self.assertEqual(self.submission.calls[0]["timeout_seconds"], 17)

    def test_runtime_and_explicit_credentials_cannot_be_mixed(self):
        credentials = PySifenRuntimeCredentials(
            adapter_config=False,
            xml_signing_credential=False,
            mutual_tls_credential=False,
            signing_certificate_bytes=b"runtime-certificate",
            signing_private_key_bytes=b"runtime-private-key",
            signing_private_key_password=None,
            csc_id="0001",
            csc_value="runtime-csc",
            endpoint_url="https://sifen-test.example.test/de",
            timeout_seconds=30,
        )

        with self.assertRaisesRegex(ValidationError, "cannot be mixed"):
            self._service().submit_test(
                document=self.document,
                payload={"payload": "fixture"},
                signing_timestamp=self.SIGNING_TIMESTAMP,
                certificate_bytes=b"explicit-certificate",
                credentials=credentials,
            )

    def test_final_xml_contains_qr_before_xsd_and_submission(self):
        self._submit()
        xsd_xml = etree.fromstring(self.xsd.calls[0])
        submission_xml = etree.fromstring(self.submission.calls[0]["final_xml_bytes"])

        self.assertIsNotNone(xsd_xml.find(f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}gCamFuFD"))
        self.assertIsNotNone(
            submission_xml.find(f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}gCamFuFD")
        )

    def test_signing_failure_stops_pipeline(self):
        self.signing.error = ValidationError("signing secret detail")

        result = self._submit()

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_stage"], "signing")
        self.assertEqual(result["error_message"], "Paraguay signing pipeline failed.")
        self.assertFalse(self.qr.calls)
        self.assertFalse(self.xsd.calls)
        self.assertFalse(self.submission.calls)

    def test_qr_failure_stops_before_xsd_and_submission(self):
        self.qr.error = ValidationError("qr failure")

        result = self._submit()

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_stage"], "qr_generation")
        self.assertFalse(self.xsd.calls)
        self.assertFalse(self.submission.calls)

    def test_final_xsd_validation_failure_stops_before_submission(self):
        self.xsd.valid = False

        result = self._submit()

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_stage"], "final_xsd_validation")
        self.assertEqual(
            result["error_message"],
            "Final signed Paraguay XML failed local SIFEN XSD validation.",
        )
        self.assertEqual(result["xsd_errors"][0]["message"], "fixture xsd error")
        self.assertFalse(self.submission.calls)

    def test_submission_failure_is_normalized(self):
        self.submission.error = ValidationError("submission secret detail")

        result = self._submit()

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_stage"], "test_submission")
        self.assertEqual(result["error_message"], "SIFEN test submission failed.")
        self.assertNotIn("secret", json.dumps(result))

    def test_rejected_submission_is_returned_without_retry_or_persistence(self):
        self.submission.outcome = "rejected"

        result = self._submit()

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_stage"], "test_submission")
        self.assertEqual(result["submission_status"], "rejected")
        self.assertEqual(result["authority_code"], "1300")
