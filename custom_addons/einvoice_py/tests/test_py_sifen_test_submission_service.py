from lxml import etree
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenConnectionError,
    PySifenSubmissionService,
    PySifenTimeoutError,
    PySifenTlsError,
    PySifenTransportError,
    PySifenTestSubmissionService,
)
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)


class _AcceptingXsdValidator:
    def validate_final_signed_xml(self, xml_content):
        return {"valid": True, "errors": [], "warnings": []}


class _RejectingXsdValidator:
    def validate_final_signed_xml(self, xml_content):
        return {
            "valid": False,
            "errors": [{"message": "fixture validation error"}],
            "warnings": [],
        }


class TestPySifenTestSubmissionService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"
    SOAP_ENV_NS = "http://www.w3.org/2003/05/soap-envelope"
    SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN Test Tenant",
            "code": "sifen-test",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.submission_sequence = self.env["ir.sequence"].create({
            "name": "SIFEN Test Submission Identifier",
            "implementation": "no_gap",
            "padding": 1,
            "number_next": 1,
            "number_increment": 1,
        })
        self.adapter = self.env["fiscal.adapter.config"].create({
            "name": "SIFEN Test Adapter",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "country_code": "PY",
            "adapter_code": "py",
            "environment": "test",
            "sequence_id": self.submission_sequence.id,
        })
        self.document = self.env["fiscal.document"].create({
            "name": "SIFEN Test Document",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "adapter_config_id": self.adapter.id,
            "customer_name": "Test Customer",
            "amount_total": 100,
            "idempotency_key": self.id(),
            "py_cdc": self.CDC,
            "py_cdc_dv": self.CDC[-1],
            "country_identifier": self.CDC,
        })
        self.transport_calls = []
        self.mutual_tls_credential = self.env["fiscal.credential"].create({
            "name": "SIFEN Test Mutual TLS Credential",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "provider_type": "external_secret",
            "material_format": "pkcs12",
            "secret_ref": "secret://sifen-test/mtls.p12",
            "password_secret_ref": "secret://sifen-test/mtls-password",
        })

    def _service(self, response=None, validator=None, transport_error=None):
        def transport(**kwargs):
            self.transport_calls.append(kwargs)
            if transport_error:
                raise transport_error
            return response or {
                "status_code": 200,
                "content": self._response_xml("0260", "Aprobado", "12345"),
            }

        return PySifenTestSubmissionService(
            xsd_validation_service=validator or _AcceptingXsdValidator(),
            transport=transport,
        )

    def _service_without_injected_transport(self, validator=None):
        return PySifenTestSubmissionService(
            xsd_validation_service=validator or _AcceptingXsdValidator(),
        )

    def _generic_service(self, response=None):
        def transport(**kwargs):
            self.transport_calls.append(kwargs)
            return response or {
                "status_code": 200,
                "content": self._response_xml("0260", "Aprobado", "12345"),
            }

        return PySifenSubmissionService(
            xsd_validation_service=_AcceptingXsdValidator(),
            transport=transport,
        )

    def _final_xml(self, *, cdc=None):
        namespace = PyUnsignedXmlBuilder.SIFEN_NS
        ds_namespace = "http://www.w3.org/2000/09/xmldsig#"
        root = etree.Element(f"{{{namespace}}}rDE", nsmap={None: namespace})
        etree.SubElement(root, f"{{{namespace}}}dVerFor").text = "150"
        de = etree.SubElement(root, f"{{{namespace}}}DE", {"Id": cdc or self.CDC})
        etree.SubElement(de, f"{{{namespace}}}dDVId").text = self.CDC[-1]
        etree.SubElement(de, f"{{{namespace}}}dFecFirma").text = "2026-06-18T12:34:56"
        etree.SubElement(de, f"{{{namespace}}}dSisFact").text = "1"
        signature = etree.SubElement(root, f"{{{ds_namespace}}}Signature")
        signed_info = etree.SubElement(signature, f"{{{ds_namespace}}}SignedInfo")
        reference = etree.SubElement(signed_info, f"{{{ds_namespace}}}Reference")
        etree.SubElement(reference, f"{{{ds_namespace}}}DigestValue").text = "digest"
        qr_group = etree.SubElement(root, f"{{{namespace}}}gCamFuFD")
        etree.SubElement(qr_group, f"{{{namespace}}}dCarQR").text = "https://example.test/qr"
        etree.indent(root, space="  ")
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    def _response_xml(self, code, message, receipt=""):
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://www.w3.org/2003/05/soap-envelope">
  <soapenv:Body>
    <ns0:rResEnviDE xmlns:ns0="http://ekuatia.set.gov.py/sifen/xsd">
      <ns0:dCodRes>{code}</ns0:dCodRes>
      <ns0:dMsgRes>{message}</ns0:dMsgRes>
      <ns0:dProtAut>{receipt}</ns0:dProtAut>
    </ns0:rResEnviDE>
  </soapenv:Body>
</soapenv:Envelope>""".encode("utf-8")

    def _submit(self, **overrides):
        response = overrides.pop("response", None)
        values = {
            "document": self.document,
            "final_xml_bytes": self._final_xml(),
            "endpoint_url": "https://sifen-test.example.test/de",
            "mutual_tls_credential": self.mutual_tls_credential,
        }
        values.update(overrides)
        return self._service(response=response).submit_final_xml(**values)

    def test_accepted_sifen_test_response_is_normalized(self):
        result = self._submit()

        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["authority_status_code"], "0260")
        self.assertEqual(result["authority_message"], "Aprobado")
        self.assertEqual(result["authority_receipt_ref"], "12345")
        self.assertEqual(result["country_identifier"], self.CDC)
        self.assertFalse(result["retryable"])
        self.assertEqual(len(result["request_hash"]), 64)
        self.assertEqual(len(result["response_hash"]), 64)

    def test_synchronous_lot_code_is_not_accepted(self):
        result = self._submit(
            response={
                "status_code": 200,
                "content": self._response_xml(
                    "0300",
                    "Lote recibido",
                    "12345",
                ),
            },
        )

        self.assertEqual(result["outcome"], "rejected")
        self.assertEqual(result["authority_status_code"], "0300")

    def test_generic_submission_service_accepts_production_document(self):
        self.document.environment = "production"
        self.adapter.environment = "production"

        result = self._generic_service().submit_final_xml(
            document=self.document,
            final_xml_bytes=self._final_xml(),
            endpoint_url="https://sifen-production.example.test/de",
            mutual_tls_credential=self.mutual_tls_credential,
        )

        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["metadata_json"]["environment"], "production")
        self.assertEqual(result["metadata_json"]["service"], "py_sifen_submission")
        self.assertEqual(len(self.transport_calls), 1)

    def test_generic_production_failure_message_is_environment_neutral(self):
        self.document.environment = "production"
        self.adapter.environment = "production"
        service = self._generic_service(response={
            "status_code": 200,
            "content": b"<not-xml",
        })

        result = service.submit_final_xml(
            document=self.document,
            final_xml_bytes=self._final_xml(),
            endpoint_url="https://sifen-production.example.test/de",
            mutual_tls_credential=self.mutual_tls_credential,
        )

        self.assertEqual(result["outcome"], "failed_final")
        self.assertIn("production", result["authority_message"].lower())
        self.assertNotIn("test", result["authority_message"].lower())
        self.assertNotIn("sandbox", result["authority_message"].lower())

    def test_soap_envelope_contains_final_xml(self):
        self._submit()
        request_xml = self.transport_calls[0]["body"]
        root = etree.fromstring(request_xml)

        self.assertEqual(root.tag, f"{{{self.SOAP_ENV_NS}}}Envelope")
        body = root.find(f"{{{self.SOAP_ENV_NS}}}Body")
        self.assertIsNotNone(body)
        request_node = body.find(f"{{{self.SIFEN_NS}}}rEnviDe")
        self.assertIsNotNone(request_node)
        self.assertEqual(
            [etree.QName(child).localname for child in request_node],
            ["dId", "xDE"],
        )
        submission_id = request_node.findtext(f"{{{self.SIFEN_NS}}}dId")
        self.assertRegex(submission_id, r"^\d{1,15}$")
        document_node = request_node.find(f"{{{self.SIFEN_NS}}}xDE")
        submitted_de = document_node.find(f"{{{self.SIFEN_NS}}}rDE")
        self.assertIsNotNone(submitted_de)
        self.assertEqual(
            submitted_de.find(f"{{{self.SIFEN_NS}}}DE").get("Id"),
            self.CDC,
        )
        self.assertIsNotNone(submitted_de.find(f"{{{self.SIFEN_NS}}}gCamFuFD"))
        self.assertEqual(
            self.transport_calls[0]["mutual_tls_credential"],
            self.mutual_tls_credential,
        )

    def test_soap_body_validates_against_official_synchronous_structure(self):
        self._submit()
        root = etree.fromstring(self.transport_calls[0]["body"])
        request_node = root.find(
            f"{{{self.SOAP_ENV_NS}}}Body/{{{self.SIFEN_NS}}}rEnviDe"
        )
        schema = etree.XMLSchema(etree.fromstring(f"""
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="{self.SIFEN_NS}"
           xmlns="{self.SIFEN_NS}"
           elementFormDefault="qualified">
  <xs:element name="rEnviDe">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="dId">
          <xs:simpleType>
            <xs:restriction base="xs:integer">
              <xs:totalDigits value="15"/>
            </xs:restriction>
          </xs:simpleType>
        </xs:element>
        <xs:element name="xDE">
          <xs:complexType>
            <xs:sequence>
              <xs:any namespace="{self.SIFEN_NS}" processContents="skip"/>
            </xs:sequence>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
""".encode("utf-8")))

        self.assertTrue(schema.validate(request_node), schema.error_log)

    def test_submission_identifier_is_persistent_sequential_and_scoped(self):
        with patch(
            "odoo.addons.einvoice_py.services.py_sifen_test_submission_service.time.time",
            return_value=1234567890,
        ):
            self._submit()
            self._submit()
        submission_ids = [
            etree.fromstring(call["body"]).findtext(
                f"{{{self.SOAP_ENV_NS}}}Body/"
                f"{{{self.SIFEN_NS}}}rEnviDe/"
                f"{{{self.SIFEN_NS}}}dId"
            )
            for call in self.transport_calls
        ]

        self.assertEqual(submission_ids, ["1", "2"])
        self.assertTrue(all(value.isdigit() for value in submission_ids))
        self.assertTrue(all(1 <= len(value) <= 15 for value in submission_ids))

        other_company = self.env["res.company"].create({
            "name": "Other SIFEN Test Company",
        })
        other_tenant = self.env["fiscal.tenant"].create({
            "name": "Other SIFEN Test Tenant",
            "code": f"other-{self.id()}",
            "company_id": other_company.id,
        })
        other_sequence = self.env["ir.sequence"].create({
            "name": "Other SIFEN Test Submission Identifier",
            "implementation": "no_gap",
            "padding": 1,
            "number_next": 1,
            "number_increment": 1,
        })
        other_adapter = self.env["fiscal.adapter.config"].create({
            "name": "Other SIFEN Test Adapter",
            "tenant_id": other_tenant.id,
            "company_id": other_company.id,
            "country_code": "PY",
            "adapter_code": "py",
            "environment": "test",
            "sequence_id": other_sequence.id,
        })
        other_document = self.document.copy({
            "name": "Other SIFEN Test Document",
            "tenant_id": other_tenant.id,
            "company_id": other_company.id,
            "adapter_config_id": other_adapter.id,
            "idempotency_key": f"other-{self.id()}",
        })
        self._service().submit_final_xml(
            document=other_document,
            final_xml_bytes=self._final_xml(),
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.mutual_tls_credential,
        )
        other_submission_id = etree.fromstring(self.transport_calls[-1]["body"]).findtext(
            f"{{{self.SOAP_ENV_NS}}}Body/"
            f"{{{self.SIFEN_NS}}}rEnviDe/"
            f"{{{self.SIFEN_NS}}}dId"
        )

        self.assertEqual(other_submission_id, "1")

    def test_local_xsd_failure_blocks_transport(self):
        service = self._service(validator=_RejectingXsdValidator())

        with self.assertRaisesRegex(ValidationError, "pass local SIFEN XSD validation"):
            service.submit_final_xml(
                document=self.document,
                final_xml_bytes=self._final_xml(),
                endpoint_url="https://sifen-test.example.test/de",
            )

        self.assertFalse(self.transport_calls)

    def test_document_must_be_paraguay_test_environment(self):
        self.document.environment = "production"

        with self.assertRaisesRegex(ValidationError, "test environment"):
            self._submit()

        self.assertFalse(self.transport_calls)

    def test_endpoint_must_be_https(self):
        with self.assertRaisesRegex(ValidationError, "HTTPS URL"):
            self._submit(endpoint_url="http://sifen-test.example.test/de")

    def test_endpoint_must_not_include_userinfo_query_or_fragment(self):
        unsafe_urls = [
            "https://user:s3cret@sifen-test.example.test/de",
            "https://sifen-test.example.test/de?token=s3cret",
            "https://sifen-test.example.test/de#token-s3cret",
        ]
        for endpoint_url in unsafe_urls:
            with self.subTest(endpoint_url=endpoint_url):
                with self.assertRaisesRegex(ValidationError, "endpoint"):
                    self._submit(endpoint_url=endpoint_url)

        self.assertFalse(self.transport_calls)

    def test_non_paraguay_document_is_rejected_before_transport(self):
        self.document.country_code = "CR"

        with self.assertRaisesRegex(ValidationError, "Paraguay document"):
            self._submit()

        self.assertFalse(self.transport_calls)

    def test_cdc_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "CDC must match"):
            self._submit(final_xml_bytes=self._final_xml(cdc=self.CDC[:-1] + "9"))

    def test_rejected_authority_response_is_normalized(self):
        service = self._service(response={
            "status_code": 200,
            "content": self._response_xml("1300", "Rechazado", ""),
        })

        result = service.submit_final_xml(
            document=self.document,
            final_xml_bytes=self._final_xml(),
            endpoint_url="https://sifen-test.example.test/de",
        )

        self.assertEqual(result["outcome"], "rejected")
        self.assertEqual(result["authority_status_code"], "1300")
        self.assertEqual(result["metadata_json"]["response_category"], "authority_response")
        self.assertFalse(result["retryable"])

    def test_connection_error_is_retryable_without_response_hash(self):
        service = self._service(
            transport_error=PySifenConnectionError("token=s3cret timeout fixture")
        )

        result = service.submit_final_xml(
            document=self.document,
            final_xml_bytes=self._final_xml(),
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.mutual_tls_credential,
        )

        self.assertEqual(result["outcome"], "failed_retryable")
        self.assertTrue(result["retryable"])
        self.assertEqual(result["response_hash"], "")
        self.assertEqual(
            result["authority_message"],
            "SIFEN test transport failed before a response was received.",
        )
        self.assertNotIn("s3cret", result["authority_message"])
        self.assertEqual(
            result["metadata_json"]["transport_error"],
            "PySifenConnectionError",
        )
        self.assertEqual(
            result["metadata_json"]["transport_error_category"],
            "connection_failure",
        )

    def test_timeout_is_marked_as_ambiguous(self):
        service = self._service(transport_error=PySifenTimeoutError())

        result = service.submit_final_xml(
            document=self.document,
            final_xml_bytes=self._final_xml(),
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.mutual_tls_credential,
        )

        self.assertTrue(result["retryable"])
        self.assertTrue(result["ambiguous"])
        self.assertEqual(
            result["metadata_json"]["transport_error_category"],
            "timeout_failure",
        )

    def test_tls_error_is_retryable_and_classified(self):
        service = self._service(transport_error=PySifenTlsError("certificate secret"))

        result = service.submit_final_xml(
            document=self.document,
            final_xml_bytes=self._final_xml(),
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.mutual_tls_credential,
        )

        self.assertEqual(result["outcome"], "failed_retryable")
        self.assertEqual(
            result["metadata_json"]["transport_error_category"],
            "tls_failure",
        )
        self.assertNotIn("certificate secret", result["authority_message"])

    def test_generic_transport_error_remains_classified(self):
        service = self._service(transport_error=PySifenTransportError("transport secret"))

        result = service.submit_final_xml(
            document=self.document,
            final_xml_bytes=self._final_xml(),
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.mutual_tls_credential,
        )

        self.assertEqual(
            result["metadata_json"]["transport_error_category"],
            "transport_failure",
        )

    def test_unexpected_transport_exception_surfaces(self):
        service = self._service(transport_error=RuntimeError("programmer bug"))

        with self.assertRaisesRegex(RuntimeError, "programmer bug"):
            service.submit_final_xml(
                document=self.document,
                final_xml_bytes=self._final_xml(),
                endpoint_url="https://sifen-test.example.test/de",
                mutual_tls_credential=self.mutual_tls_credential,
            )

    def test_default_transport_rejects_mutual_tls_sandbox_use(self):
        service = self._service_without_injected_transport()

        with self.assertRaisesRegex(ValidationError, "PySifenSandboxTransport"):
            service.submit_final_xml(
                document=self.document,
                final_xml_bytes=self._final_xml(),
                endpoint_url="https://sifen-test.example.test/de",
                mutual_tls_credential=self.mutual_tls_credential,
            )

    def test_malformed_sifen_response_is_safe_and_hashed(self):
        service = self._service(response={
            "status_code": 200,
            "content": b"<not-xml",
        })

        result = service.submit_final_xml(
            document=self.document,
            final_xml_bytes=self._final_xml(),
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.mutual_tls_credential,
        )

        self.assertEqual(result["outcome"], "failed_final")
        self.assertFalse(result["retryable"])
        self.assertEqual(result["authority_message"], "Malformed SIFEN test response.")
        self.assertEqual(len(result["response_hash"]), 64)
        self.assertNotIn("<not-xml", result["authority_message"])

    def test_soap_fault_is_retryable_and_normalized(self):
        fault = b"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://www.w3.org/2003/05/soap-envelope">
  <soapenv:Body>
    <soapenv:Fault>
      <faultcode>soapenv:Server</faultcode>
      <faultstring>Temporary SIFEN fault</faultstring>
    </soapenv:Fault>
  </soapenv:Body>
</soapenv:Envelope>"""
        service = self._service(response={"status_code": 500, "content": fault})

        result = service.submit_final_xml(
            document=self.document,
            final_xml_bytes=self._final_xml(),
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.mutual_tls_credential,
        )

        self.assertEqual(result["outcome"], "failed_retryable")
        self.assertEqual(result["authority_status_code"], "soapenv:Server")
        self.assertTrue(result["metadata_json"]["soap_fault"])
        self.assertIn("Temporary SIFEN fault", result["authority_message"])

    def test_http_failure_response_is_classified(self):
        service = self._service(response={
            "status_code": 503,
            "content": b"<html>unavailable</html>",
        })

        result = service.submit_final_xml(
            document=self.document,
            final_xml_bytes=self._final_xml(),
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.mutual_tls_credential,
        )

        self.assertEqual(result["outcome"], "failed_retryable")
        self.assertEqual(result["metadata_json"]["response_category"], "http_failure")
