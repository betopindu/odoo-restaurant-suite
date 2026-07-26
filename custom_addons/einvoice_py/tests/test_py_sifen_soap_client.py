from dataclasses import FrozenInstanceError

from odoo.exceptions import ValidationError
from odoo.tests.common import BaseCase

from odoo.addons.einvoice_py.services.py_sifen_soap_client import (
    PySifenSoapClient,
)
from odoo.addons.einvoice_py.services.py_sifen_sandbox_transport import (
    PySifenSandboxTransport,
)
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenConnectionError,
    PySifenDnsError,
    PySifenTimeoutError,
    PySifenTlsError,
)


class _XsdValidationStub:
    def __init__(self, valid=True):
        self.valid = valid

    def validate_final_signed_xml(self, xml_content):
        return {"valid": self.valid, "errors": []}


class _Transport:
    def __init__(self, response=None, error=None):
        self.response = response or {
            "status_code": 200,
            "content": b"<response/>",
            "headers": {"Content-Type": "application/soap+xml"},
        }
        self.error = error
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class _Clock:
    def __init__(self):
        self.values = iter((10.0, 10.125))

    def __call__(self):
        return next(self.values)


class TestPySifenSoapClient(BaseCase):
    CDC = "01444444017001001001452822017012515873260988"
    ENDPOINT = "https://sifen-test.example.test/de/ws/sync/recibe.wsdl"
    SECRET_MARKERS = (
        "pkcs12-secret-bytes",
        "private-key-secret",
        "password-secret",
        "certificate-secret",
    )

    def test_default_transport_reuses_supplied_provider_registry(self):
        registry = object()

        client = PySifenSoapClient(
            object(),
            provider_registry=registry,
            xsd_validation_service=_XsdValidationStub(),
        )

        self.assertIsInstance(client.transport, PySifenSandboxTransport)
        self.assertIs(client.transport.provider_registry, registry)

    def test_successful_post_preserves_request_and_returns_immutable_result(self):
        transport = _Transport(response={
            "status_code": 200,
            "content": b"<response><ok>true</ok></response>",
            "headers": {"X-Request": "accepted"},
        })
        clock = _Clock()

        result = self._client(transport, clock=clock).submit(
            soap_xml_bytes=self._envelope(),
            endpoint_url=self.ENDPOINT,
            mutual_tls_credential=object(),
            timeout_seconds=19,
        )

        self.assertEqual(result.category, "success")
        self.assertEqual(result.http_status, 200)
        self.assertEqual(result.elapsed_ms, 125)
        self.assertEqual(result.endpoint_url, self.ENDPOINT)
        self.assertEqual(result.request_identifier, "17")
        self.assertEqual(result.response_headers, (("X-Request", "accepted"),))
        self.assertEqual(
            result.raw_response_bytes,
            b"<response><ok>true</ok></response>",
        )
        self.assertIsNotNone(result.parsed_xml)
        with self.assertRaises(FrozenInstanceError):
            result.category = "changed"
        call = transport.calls[0]
        self.assertEqual(call["body"], self._envelope())
        self.assertEqual(call["endpoint_url"], self.ENDPOINT)
        self.assertEqual(call["timeout_seconds"], 19)
        self.assertIsNone(call["soap_action"])

    def test_network_failure_categories_are_safe(self):
        cases = (
            (PySifenTimeoutError(), "timeout"),
            (PySifenDnsError(), "dns_failure"),
            (PySifenTlsError(), "tls_handshake_failure"),
            (PySifenConnectionError(), "connection_failure"),
            (ValidationError("private-key-secret"), "certificate_validation_failure"),
        )
        for error, category in cases:
            with self.subTest(category=category):
                result = self._client(_Transport(error=error)).submit(
                    soap_xml_bytes=self._envelope(),
                    endpoint_url=self.ENDPOINT,
                    mutual_tls_credential=object(),
                )
                self.assertEqual(result.category, category)
                self.assertEqual(result.http_status, 0)
                self.assertEqual(result.raw_response_bytes, b"")
                self._assert_secret_free(result.error_message)

    def test_http_error_preserves_body_and_headers(self):
        body = b"<response><error>unavailable</error></response>"
        result = self._client(_Transport(response={
            "status_code": 503,
            "content": body,
            "headers": {"Retry-After": "30"},
        })).submit(
            soap_xml_bytes=self._envelope(),
            endpoint_url=self.ENDPOINT,
            mutual_tls_credential=object(),
        )

        self.assertEqual(result.category, "http_error")
        self.assertEqual(result.http_status, 503)
        self.assertEqual(result.raw_response_bytes, body)
        self.assertEqual(result.response_headers, (("Retry-After", "30"),))

    def test_soap_fault_is_distinct_and_preserves_raw_body(self):
        body = b"""<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope">
<Body><Fault><Code><Value>Sender</Value></Code></Fault></Body></Envelope>"""
        result = self._client(_Transport(response={
            "status_code": 500,
            "content": body,
            "headers": {},
        })).submit(
            soap_xml_bytes=self._envelope(),
            endpoint_url=self.ENDPOINT,
            mutual_tls_credential=object(),
        )

        self.assertEqual(result.category, "soap_fault")
        self.assertEqual(result.raw_response_bytes, body)
        self.assertIsNotNone(result.parsed_xml)

    def test_malformed_xml_response_is_distinct_and_preserved(self):
        body = b"<not-xml"
        result = self._client(_Transport(response={
            "status_code": 200,
            "content": body,
            "headers": {},
        })).submit(
            soap_xml_bytes=self._envelope(),
            endpoint_url=self.ENDPOINT,
            mutual_tls_credential=object(),
        )

        self.assertEqual(result.category, "malformed_xml_response")
        self.assertEqual(result.raw_response_bytes, body)
        self.assertIsNone(result.parsed_xml)

    def test_invalid_envelope_unsigned_and_xsd_invalid_are_rejected_before_post(self):
        invalid_transport = _Transport()
        invalid_inputs = (
            b"<not-soap/>",
            self._envelope().replace(
                b'<Signature xmlns="http://www.w3.org/2000/09/xmldsig#"/>',
                b"",
            ),
        )
        for soap_xml in invalid_inputs:
            with self.subTest(soap_xml=soap_xml[:20]):
                with self.assertRaises(ValidationError):
                    self._client(invalid_transport).submit(
                        soap_xml_bytes=soap_xml,
                        endpoint_url=self.ENDPOINT,
                        mutual_tls_credential=object(),
                    )
        with self.assertRaisesRegex(ValidationError, "XSD validation"):
            self._client(
                invalid_transport,
                validator=_XsdValidationStub(valid=False),
            ).submit(
                soap_xml_bytes=self._envelope(),
                endpoint_url=self.ENDPOINT,
                mutual_tls_credential=object(),
            )
        self.assertFalse(invalid_transport.calls)

    def test_request_transmission_is_deterministic_and_nothing_is_logged(self):
        first_transport = _Transport()
        second_transport = _Transport()

        first = self._client(first_transport).submit(
            soap_xml_bytes=self._envelope(),
            endpoint_url=self.ENDPOINT,
            mutual_tls_credential=object(),
        )
        second = self._client(second_transport).submit(
            soap_xml_bytes=self._envelope(),
            endpoint_url=self.ENDPOINT,
            mutual_tls_credential=object(),
        )

        self.assertEqual(
            first_transport.calls[0]["body"],
            second_transport.calls[0]["body"],
        )
        self.assertEqual(first.raw_response_bytes, second.raw_response_bytes)
        self._assert_secret_free(repr(first))
        self._assert_secret_free(str(first))

    def _client(self, transport, *, validator=None, clock=None):
        return PySifenSoapClient(
            None,
            transport=transport,
            xsd_validation_service=validator or _XsdValidationStub(),
            clock=clock,
        )

    def _assert_secret_free(self, value):
        for marker in self.SECRET_MARKERS:
            self.assertNotIn(marker, value)

    def _envelope(self):
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope"><Header/><Body>
<rEnviDe xmlns="http://ekuatia.set.gov.py/sifen/xsd"><dId>17</dId><xDE>
<rDE><dVerFor>150</dVerFor><DE Id="{self.CDC}"/><Signature xmlns="http://www.w3.org/2000/09/xmldsig#"/><gCamFuFD><dCarQR>https://example.test/qr</dCarQR></gCamFuFD></rDE>
</xDE></rEnviDe></Body></Envelope>""".encode("utf-8")
