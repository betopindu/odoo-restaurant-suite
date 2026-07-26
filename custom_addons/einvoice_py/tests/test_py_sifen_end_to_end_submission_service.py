from types import SimpleNamespace

from odoo.exceptions import ValidationError
from odoo.tests.common import BaseCase

from odoo.addons.einvoice_py.services.py_sifen_recep_de_response_parser import (
    PySifenRecepDeClassification,
    PySifenRecepDeResponseResult,
)
from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
    PySifenRuntimeCredentials,
)
from odoo.addons.einvoice_py.services.py_sifen_soap_client import (
    PySifenSoapClientResult,
)
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenSubmissionFailureResult,
    PySifenSubmissionService,
)


class _Document:
    country_code = "PY"
    environment = "test"

    def __init__(self):
        scope = object()
        self.tenant_id = scope
        self.company_id = scope
        self.adapter_config_id = SimpleNamespace(
            tenant_id=scope,
            company_id=scope,
            environment="test",
            sequence_id=_Sequence(),
        )

    def ensure_one(self):
        return self


class _Sequence:
    def next_by_id(self):
        return "17"


class _Component:
    def __init__(self, events, name, result=None, error=None):
        self.events = events
        self.name = name
        self.result = result
        self.error = error
        self.calls = []

    def _call(self, kwargs):
        self.events.append(self.name)
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class _UnsignedBuilder(_Component):
    def build_from_payload(self, payload):
        return self._call({"payload": payload})


class _PreparationService(_Component):
    def prepare(self, document, unsigned_xml_bytes, signing_timestamp):
        return self._call({
            "document": document,
            "unsigned_xml_bytes": unsigned_xml_bytes,
            "signing_timestamp": signing_timestamp,
        })


class _SignatureService(_Component):
    def sign(self, **kwargs):
        return self._call(kwargs)


class _QrBuilder(_Component):
    def build(self, **kwargs):
        return self._call(kwargs)


class _Assembler(_Component):
    def assemble(self, **kwargs):
        return self._call(kwargs)


class _EnvelopeBuilder(_Component):
    def build(self, **kwargs):
        return self._call(kwargs)


class _SoapClient(_Component):
    def submit(self, **kwargs):
        return self._call(kwargs)


class _CredentialProvider:
    def __init__(self, credentials):
        self.credentials = credentials
        self.calls = []

    def resolve(self, **kwargs):
        self.calls.append(kwargs)
        return self.credentials


class _Logger:
    def __init__(self):
        self.entries = []

    def debug(self, message, *args):
        self.entries.append(message % args)


class TestPySifenEndToEndSubmissionService(BaseCase):
    SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
    SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
    CDC = "01444444017001001001452822017012515873260988"
    ENDPOINT = "https://sifen-test.example.test/de/ws/sync/recibe.wsdl"
    SECRET_MARKERS = (
        "private-key-secret",
        "certificate-secret",
        "password-secret",
        "csc-secret",
    )

    def setUp(self):
        super().setUp()
        self.events = []
        self.document = _Document()
        self.credentials = PySifenRuntimeCredentials(
            adapter_config=False,
            xml_signing_credential=False,
            signing_certificate_bytes=b"certificate-secret",
            signing_private_key_bytes=b"private-key-secret",
            signing_private_key_password=b"password-secret",
            csc_id="0001",
            csc_value="csc-secret",
            endpoint_url=self.ENDPOINT,
            mutual_tls_credential=object(),
            timeout_seconds=30,
        )
        self.provider = _CredentialProvider(self.credentials)
        self.unsigned = _UnsignedBuilder(
            self.events,
            "unsigned_xml",
            b"unsigned",
        )
        self.preparation = _PreparationService(
            self.events,
            "cdc_preparation",
            {
                "prepared_xml_bytes": b"prepared",
                "cdc": self.CDC,
            },
        )
        self.signature = _SignatureService(
            self.events,
            "xmldsig",
            SimpleNamespace(
                signed_xml_bytes=b"signed",
                cdc=self.CDC,
                digest_value="digest",
            ),
        )
        self.qr = _QrBuilder(
            self.events,
            "qr",
            SimpleNamespace(
                gcamfufd_xml_bytes=b"qr-group",
                qr_string="https://example.test/qr",
            ),
        )
        self.assembler = _Assembler(
            self.events,
            "rde_xsd",
            SimpleNamespace(
                final_xml_bytes=b"final-rde",
                xsd_valid=True,
                validation_errors=(),
            ),
        )
        self.envelope = _EnvelopeBuilder(
            self.events,
            "soap",
            SimpleNamespace(soap_xml_bytes=b"soap-envelope"),
        )
        self.client = _SoapClient(
            self.events,
            "https_post",
            self._client_result(self._business_response(
                status="Aprobado",
                code="0260",
                message="Autorización del DE satisfactoria",
            )),
        )
        self.logger = _Logger()

    def test_successful_end_to_end_flow_returns_parsed_immutable_response(self):
        result = self._service().submit(
            document=self.document,
            payload={"fixture": True},
            signing_timestamp="2026-07-26 12:00:00",
        )

        self.assertIsInstance(result, PySifenRecepDeResponseResult)
        self.assertEqual(
            result.classification,
            PySifenRecepDeClassification.ACCEPTED,
        )
        self.assertEqual(result.result_code, "0260")
        self.assertEqual(
            self.events,
            [
                "unsigned_xml",
                "cdc_preparation",
                "xmldsig",
                "qr",
                "rde_xsd",
                "soap",
                "https_post",
            ],
        )
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(
            self.envelope.calls[0]["validated_rde_bytes"],
            b"final-rde",
        )
        self.assertEqual(self.envelope.calls[0]["submission_id"], "17")
        self.assertEqual(
            self.client.calls[0]["soap_xml_bytes"],
            b"soap-envelope",
        )
        self.assertEqual(
            self.client.calls[0]["mutual_tls_credential"],
            self.credentials.mutual_tls_credential,
        )
        logs = "\n".join(self.logger.entries)
        for marker in self.SECRET_MARKERS:
            self.assertNotIn(marker, logs)

    def test_build_signature_qr_xsd_and_soap_failures_are_structured(self):
        cases = (
            (self.unsigned, "build", "build_failure"),
            (self.signature, "signing", "signature_failure"),
            (self.qr, "qr", "qr_failure"),
            (self.envelope, "soap", "soap_generation_failure"),
        )
        for component, stage, category in cases:
            with self.subTest(stage=stage):
                component.error = ValidationError("secret failure detail")
                result = self._service().submit(
                    document=self.document,
                    payload={"fixture": True},
                    signing_timestamp="2026-07-26 12:00:00",
                )
                self.assertIsInstance(result, PySifenSubmissionFailureResult)
                self.assertEqual(result.stage, stage)
                self.assertEqual(result.category, category)
                self.assertNotIn("secret", result.message)
                component.error = None
                self.events.clear()

        self.assembler.result = SimpleNamespace(
            final_xml_bytes=b"invalid-rde",
            xsd_valid=False,
            validation_errors=(object(),),
        )
        result = self._service().submit(
            document=self.document,
            payload={"fixture": True},
            signing_timestamp="2026-07-26 12:00:00",
        )
        self.assertEqual(result.stage, "xsd_validation")
        self.assertEqual(result.category, "xsd_validation_failure")
        self.assertNotIn("soap", self.events)
        self.assertNotIn("https_post", self.events)

    def test_transport_failure_is_structured_and_not_parsed_as_authority_result(self):
        self.client.result = self._client_result(
            b"",
            status=0,
            category="timeout",
            error_message="SIFEN TEST request timed out.",
        )

        result = self._service().submit(
            document=self.document,
            payload={"fixture": True},
            signing_timestamp="2026-07-26 12:00:00",
        )

        self.assertIsInstance(result, PySifenSubmissionFailureResult)
        self.assertEqual(result.stage, "transport")
        self.assertEqual(result.category, "timeout")
        self.assertEqual(result.message, "SIFEN TEST request timed out.")

    def test_soap_fault_and_business_rejection_remain_parsed_responses(self):
        cases = (
            (
                self._soap_fault(),
                500,
                PySifenRecepDeClassification.SOAP_FAULT,
            ),
            (
                self._business_response(
                    status="Rechazado",
                    code="0160",
                    message="XML malformado",
                ),
                200,
                PySifenRecepDeClassification.REJECTED,
            ),
        )
        for raw, status, classification in cases:
            with self.subTest(classification=classification):
                self.client.result = self._client_result(raw, status=status)
                result = self._service().submit(
                    document=self.document,
                    payload={"fixture": True},
                    signing_timestamp="2026-07-26 12:00:00",
                )
                self.assertIsInstance(result, PySifenRecepDeResponseResult)
                self.assertEqual(result.classification, classification)
                self.events.clear()

    def test_supplied_credentials_bypass_provider(self):
        result = self._service().submit(
            document=self.document,
            payload={"fixture": True},
            signing_timestamp="2026-07-26 12:00:00",
            credentials=self.credentials,
        )

        self.assertEqual(
            result.classification,
            PySifenRecepDeClassification.ACCEPTED,
        )
        self.assertFalse(self.provider.calls)

    def _service(self):
        return PySifenSubmissionService(
            env=object(),
            credential_provider=self.provider,
            unsigned_xml_builder=self.unsigned,
            signed_xml_preparation_service=self.preparation,
            xml_signature_service=self.signature,
            qr_builder=self.qr,
            rde_assembler=self.assembler,
            soap_envelope_builder=self.envelope,
            soap_client=self.client,
            debug_logger=self.logger,
        )

    def _client_result(
        self,
        raw,
        *,
        status=200,
        category="success",
        error_message="",
    ):
        return PySifenSoapClientResult(
            http_status=status,
            response_headers=(("Content-Type", "application/soap+xml"),),
            raw_response_bytes=raw,
            parsed_xml=None,
            elapsed_ms=25,
            endpoint_url=self.ENDPOINT,
            request_identifier="17",
            category=category,
            error_message=error_message,
        )

    def _business_response(self, *, status, code, message):
        return f"""<env:Envelope xmlns:env="{self.SOAP_NS}">
<env:Body><s:rRetEnviDe xmlns:s="{self.SIFEN_NS}"><s:rProtDe>
<s:Id>{self.CDC}</s:Id>
<s:dFecProc>2026-07-26T12:00:00</s:dFecProc>
<s:dEstRes>{status}</s:dEstRes>
<s:dProtAut>1234567890</s:dProtAut>
<s:gResProc><s:dCodRes>{code}</s:dCodRes>
<s:dMsgRes>{message}</s:dMsgRes></s:gResProc>
</s:rProtDe></s:rRetEnviDe></env:Body></env:Envelope>""".encode()

    def _soap_fault(self):
        return f"""<env:Envelope xmlns:env="{self.SOAP_NS}">
<env:Body><env:Fault><env:Code><env:Value>env:Sender</env:Value>
</env:Code><env:Reason><env:Text xml:lang="es">Solicitud inválida</env:Text>
</env:Reason></env:Fault></env:Body></env:Envelope>""".encode()
