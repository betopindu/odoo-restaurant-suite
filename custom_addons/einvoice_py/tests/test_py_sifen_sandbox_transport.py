import json
import socket
import ssl
from io import BytesIO
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib import error

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_module.services.credential_provider import (
    FiscalCredentialMaterialProvider,
)
from odoo.addons.einvoice_py.services.py_sifen_sandbox_transport import (
    PySifenSandboxTransport,
)
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenConnectionError,
    PySifenDnsError,
    PySifenTcpError,
    PySifenTlsError,
)


class _Registry:
    def __init__(self, material):
        self.material = material
        self.loaded_credentials = []

    def get_provider(self, credential):
        self.loaded_credentials.append(credential)
        return _Provider(self.material)


class _Provider(FiscalCredentialMaterialProvider):
    provider_type = "external_secret"

    def __init__(self, material):
        self.material = material

    def load_material(self, credential):
        return self.material


class _Response:
    code = 200
    headers = {"Content-Type": "text/xml"}

    def __init__(self, content=b"<ok/>"):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def getcode(self):
        return self.code

    def read(self):
        return self.content


class TestPySifenSandboxTransport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN Sandbox Transport Tenant",
            "code": "sifen-sandbox-transport",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self.certificate = self._certificate(self.private_key)
        self.credential = self._credential()
        self.document = self.env["fiscal.document"].create({
            "name": "SIFEN Sandbox Transport Document",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Sandbox Customer",
            "amount_total": 100,
            "idempotency_key": self.id(),
        })
        self.urlopen_calls = []

    def _credential(self, **overrides):
        values = {
            "name": "SIFEN Sandbox Mutual TLS",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "provider_type": "external_secret",
            "material_format": "pem_pair",
            "secret_ref": "secret://sifen-sandbox/mtls.pem",
            "password_secret_ref": "secret://sifen-sandbox/password",
        }
        values.update(overrides)
        return self.env["fiscal.credential"].create(values)

    def _certificate(self, private_key):
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "SIFEN Sandbox Fixture"),
        ])
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2026, 7, 4) - timedelta(days=1))
            .not_valid_after(datetime(2026, 7, 4) + timedelta(days=30))
            .sign(private_key=private_key, algorithm=hashes.SHA256())
        )

    def _pem_material(self):
        return {
            "certificate_bytes": self.certificate.public_bytes(serialization.Encoding.PEM),
            "private_key_bytes": self.private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        }

    def _pkcs12_material(self):
        return {
            "pkcs12_bytes": pkcs12.serialize_key_and_certificates(
                b"sifen-sandbox",
                self.private_key,
                self.certificate,
                None,
                serialization.NoEncryption(),
            ),
        }

    def _transport(self, material=None, urlopen=None):
        return PySifenSandboxTransport(
            self.env,
            provider_registry=_Registry(material or self._pem_material()),
            urlopen=urlopen or self._urlopen_response,
        )

    def _configured_adapter(self, *, inspection_status="valid", errors=None):
        adapter = self.env["fiscal.adapter.config"].create({
            "name": "SIFEN TEST mTLS Preflight",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "country_code": "PY",
            "adapter_code": "py",
            "environment": "test",
            "credentials_mode": "external_secret",
            "endpoint_base_url": "https://sifen-test.example.test/de",
        })
        self.credential.write({
            "inspection_status": inspection_status,
            "inspection_report_json": json.dumps({
                "errors": errors or [],
            }),
        })
        self.env["fiscal.adapter.credential.binding"].create({
            "adapter_config_id": adapter.id,
            "credential_id": self.credential.id,
            "role": "mutual_tls",
        })
        self.document.adapter_config_id = adapter
        return adapter

    def _urlopen_response(self, *args, **kwargs):
        self.urlopen_calls.append((args, kwargs))
        return _Response()

    def test_pem_pair_transport_posts_with_mutual_tls_context(self):
        result = self._transport()(
            endpoint_url="https://sifen-test.example.test/de",
            body=b"<soap/>",
            soap_action="submit",
            timeout_seconds=12,
            mutual_tls_credential=self.credential,
        )

        self.assertEqual(result["status_code"], 200)
        args, kwargs = self.urlopen_calls[0]
        self.assertEqual(args[0].full_url, "https://sifen-test.example.test/de")
        self.assertEqual(
            args[0].headers["Content-type"],
            'application/soap+xml; charset=utf-8; action="submit"',
        )
        self.assertNotIn("Soapaction", args[0].headers)
        self.assertEqual(kwargs["timeout"], 12)
        self.assertIsInstance(kwargs["context"], ssl.SSLContext)

    def test_endpoint_must_be_https_when_transport_called_directly(self):
        with self.assertRaisesRegex(ValidationError, "HTTPS URL"):
            self._transport()(
                endpoint_url="http://sifen-test.example.test/de",
                body=b"<soap/>",
                mutual_tls_credential=self.credential,
            )

        self.assertFalse(self.urlopen_calls)

    def test_endpoint_must_not_include_userinfo_query_or_fragment(self):
        unsafe_urls = [
            "https://user:s3cret@sifen-test.example.test/de",
            "https://sifen-test.example.test/de?token=s3cret",
            "https://sifen-test.example.test/de#token-s3cret",
        ]
        for endpoint_url in unsafe_urls:
            with self.subTest(endpoint_url=endpoint_url):
                with self.assertRaisesRegex(ValidationError, "endpoint"):
                    self._transport()(
                        endpoint_url=endpoint_url,
                        body=b"<soap/>",
                        mutual_tls_credential=self.credential,
                    )

        self.assertFalse(self.urlopen_calls)

    def test_pkcs12_transport_material_is_supported(self):
        credential = self._credential(
            name="SIFEN Sandbox PKCS12",
            material_format="pkcs12",
            secret_ref="secret://sifen-sandbox/mtls.p12",
        )

        result = self._transport(material=self._pkcs12_material())(
            endpoint_url="https://sifen-test.example.test/de",
            body=b"<soap/>",
            mutual_tls_credential=credential,
        )

        self.assertEqual(result["status_code"], 200)

    def test_missing_mutual_tls_credential_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "mutual TLS credential"):
            self._transport()(
                endpoint_url="https://sifen-test.example.test/de",
                body=b"<soap/>",
            )

    def test_incomplete_material_is_rejected_without_secret_output(self):
        with self.assertRaisesRegex(ValidationError, "incomplete"):
            self._transport(material={"certificate_bytes": b"secret-cert"})(
                endpoint_url="https://sifen-test.example.test/de",
                body=b"<soap/>",
                mutual_tls_credential=self.credential,
            )

    def test_tls_failure_is_classified(self):
        def urlopen(*args, **kwargs):
            raise error.URLError(ssl.SSLError("tls secret detail"))

        with self.assertRaises(PySifenTlsError):
            self._transport(urlopen=urlopen)(
                endpoint_url="https://sifen-test.example.test/de",
                body=b"<soap/>",
                mutual_tls_credential=self.credential,
            )

    def test_connection_failure_is_classified(self):
        def urlopen(*args, **kwargs):
            raise socket.timeout("connection secret detail")

        with self.assertRaises(PySifenTcpError):
            self._transport(urlopen=urlopen)(
                endpoint_url="https://sifen-test.example.test/de",
                body=b"<soap/>",
                mutual_tls_credential=self.credential,
            )

    def test_http_error_returns_response_for_normalization(self):
        def urlopen(*args, **kwargs):
            raise error.HTTPError(
                "https://sifen-test.example.test/de",
                503,
                "unavailable",
                {},
                BytesIO(b"<html>unavailable</html>"),
            )

        result = self._transport(urlopen=urlopen)(
            endpoint_url="https://sifen-test.example.test/de",
            body=b"<soap/>",
            mutual_tls_credential=self.credential,
        )

        self.assertEqual(result["status_code"], 503)

    def test_verify_connection_success_uses_head_and_mtls_context(self):
        result = self._transport().verify_connection(
            endpoint_url="https://sifen-test.example.test/de",
            timeout_seconds=5,
            mutual_tls_credential=self.credential,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["category"], "endpoint_reachable")
        self.assertEqual(result["http_status"], 200)
        self.assertTrue(result["tls_handshake_succeeded"])
        self.assertTrue(result["client_certificate_configured"])
        self.assertTrue(result["server_certificate_verified"])
        self.assertEqual(result["error_class"], "")
        args, kwargs = self.urlopen_calls[0]
        self.assertEqual(args[0].get_method(), "HEAD")
        self.assertEqual(args[0].data, None)
        self.assertEqual(kwargs["timeout"], 5)
        self.assertIsInstance(kwargs["context"], ssl.SSLContext)

    def test_verify_document_connection_delegates_resolved_configuration(self):
        credentials = SimpleNamespace(
            endpoint_url="https://sifen-test.example.test/de",
            timeout_seconds=7,
            mutual_tls_credential=self.credential,
        )

        class _FalseyCredentialProvider:
            def __init__(self):
                self.resolve = Mock(return_value=credentials)

            def __bool__(self):
                return False

        credential_provider = _FalseyCredentialProvider()
        transport = self._transport()
        expected = {
            "ok": True,
            "category": "endpoint_reachable",
            "http_status": 200,
            "tls_handshake_succeeded": True,
        }

        with patch.object(
            transport,
            "verify_connection",
            return_value=expected,
        ) as verify_connection:
            result = transport.verify_document_connection(
                self.document,
                credential_provider=credential_provider,
            )

        self.assertIs(result, expected)
        credential_provider.resolve.assert_called_once_with(document=self.document)
        verify_connection.assert_called_once_with(
            endpoint_url="https://sifen-test.example.test/de",
            timeout_seconds=7,
            mutual_tls_credential=self.credential,
        )
        self.assertEqual(self.urlopen_calls, [])

    def test_verify_document_connection_defaults_credential_provider(self):
        credentials = SimpleNamespace(
            endpoint_url="https://sifen-test.example.test/de",
            timeout_seconds=8,
            mutual_tls_credential=self.credential,
        )
        transport = self._transport()

        with patch(
            "odoo.addons.einvoice_py.services.py_sifen_sandbox_transport."
            "PySifenCredentialProvider"
        ) as provider_class, patch.object(
            transport,
            "verify_connection",
            return_value={"ok": True},
        ):
            provider_class.return_value.resolve.return_value = credentials
            transport.verify_document_connection(self.document)

        provider_class.assert_called_once_with(
            self.env,
            provider_registry=transport.provider_registry,
        )
        provider_class.return_value.resolve.assert_called_once_with(
            document=self.document,
        )

    def test_verify_document_connection_rejects_non_test_or_non_paraguay(self):
        credential_provider = Mock()
        transport = self._transport()

        self.document.environment = "production"
        production_result = transport.verify_document_connection(
            self.document,
            credential_provider=credential_provider,
        )

        self.document.environment = "test"
        self.document.country_code = "AR"
        country_result = transport.verify_document_connection(
            self.document,
            credential_provider=credential_provider,
        )

        self.assertEqual(production_result["category"], "configuration_invalid")
        self.assertEqual(country_result["category"], "configuration_invalid")
        credential_provider.resolve.assert_not_called()
        self.assertEqual(self.urlopen_calls, [])

    def test_verify_document_connection_failures_are_sanitized(self):
        transport = self._transport()
        credential_provider = Mock()
        credential_provider.resolve.side_effect = RuntimeError(
            "secret credential provider detail"
        )

        resolution_result = transport.verify_document_connection(
            self.document,
            credential_provider=credential_provider,
        )

        credential_provider.resolve.side_effect = None
        credential_provider.resolve.return_value = SimpleNamespace(
            endpoint_url="https://sifen-test.example.test/de",
            timeout_seconds=7,
            mutual_tls_credential=self.credential,
        )
        with patch.object(
            transport,
            "verify_connection",
            side_effect=ValidationError("secret material parser detail"),
        ):
            verification_result = transport.verify_document_connection(
                self.document,
                credential_provider=credential_provider,
            )

        self.assertEqual(
            resolution_result["category"],
            "configuration_invalid",
        )
        self.assertEqual(
            verification_result["category"],
            "configuration_invalid",
        )
        self.assertNotIn("secret", str(resolution_result))
        self.assertNotIn("secret", str(verification_result))
        self.assertEqual(self.urlopen_calls, [])

    def test_verify_connection_uses_default_timeout_when_omitted(self):
        transport = self._transport()

        transport.verify_connection(
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.credential,
        )

        _args, kwargs = self.urlopen_calls[0]
        self.assertEqual(kwargs["timeout"], transport.DEFAULT_VERIFY_TIMEOUT_SECONDS)

    def test_verify_connection_http_failure_keeps_tls_success(self):
        def urlopen(*args, **kwargs):
            raise error.HTTPError(
                "https://sifen-test.example.test/de",
                405,
                "method not allowed",
                {},
                BytesIO(b""),
            )

        result = self._transport(urlopen=urlopen).verify_connection(
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.credential,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["category"], "http_response_received")
        self.assertEqual(result["http_status"], 405)
        self.assertTrue(result["tls_handshake_succeeded"])

    def test_verify_connection_dns_failure_is_sanitized(self):
        def urlopen(*args, **kwargs):
            raise error.URLError(socket.gaierror("secret dns detail"))

        result = self._transport(urlopen=urlopen).verify_connection(
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.credential,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["category"], "dns_failure")
        self.assertEqual(result["error_class"], "PySifenDnsError")
        self.assertNotIn("secret", result["message"])

    def test_verify_connection_tcp_failure_is_sanitized(self):
        def urlopen(*args, **kwargs):
            raise error.URLError(ConnectionRefusedError("secret tcp detail"))

        result = self._transport(urlopen=urlopen).verify_connection(
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.credential,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["category"], "tcp_failure")
        self.assertEqual(result["error_class"], "PySifenTcpError")
        self.assertNotIn("secret", result["message"])

    def test_verify_connection_tls_failure_is_sanitized(self):
        def urlopen(*args, **kwargs):
            raise error.URLError(ssl.SSLError("secret tls detail"))

        result = self._transport(urlopen=urlopen).verify_connection(
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.credential,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["category"], "tls_failure")
        self.assertEqual(result["error_class"], "PySifenTlsError")
        self.assertNotIn("secret", result["message"])

    def test_verify_connection_distinguishes_server_trust_failure(self):
        verification_error = ssl.SSLCertVerificationError(
            1,
            "sensitive server certificate detail",
        )

        def urlopen(*args, **kwargs):
            raise error.URLError(verification_error)

        result = self._transport(urlopen=urlopen).verify_connection(
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.credential,
        )

        self.assertEqual(result["category"], "server_certificate_untrusted")
        self.assertNotIn("sensitive", json.dumps(result))

    def test_verify_connection_distinguishes_client_certificate_rejection(self):
        rejection = ssl.SSLError(1, "sensitive client certificate detail")
        rejection.reason = "TLSV1_ALERT_UNKNOWN_CA"

        def urlopen(*args, **kwargs):
            raise error.URLError(rejection)

        result = self._transport(urlopen=urlopen).verify_connection(
            endpoint_url="https://sifen-test.example.test/de",
            mutual_tls_credential=self.credential,
        )

        self.assertEqual(result["category"], "client_certificate_rejected")
        self.assertNotIn("sensitive", json.dumps(result))

    def test_document_preflight_classifies_installed_credential_failures(self):
        scenarios = (
            (
                "credential_password_invalid",
                ["Certificate material could not be parsed or decrypted."],
            ),
            (
                "certificate_expired",
                ["Certificate is expired at the inspection time."],
            ),
            (
                "credential_invalid",
                ["Certificate must be an end-entity certificate, not a CA."],
            ),
        )
        credential_provider = Mock()
        for category, errors in scenarios:
            with self.subTest(category=category):
                adapter = self._configured_adapter(
                    inspection_status="invalid",
                    errors=errors,
                )

                result = self._transport().verify_document_connection(
                    self.document,
                    credential_provider=credential_provider,
                )

                self.assertEqual(result["category"], category)
                credential_provider.resolve.assert_not_called()
                persisted = json.loads(adapter.metadata_json)[
                    "sifen_test_mtls_preflight"
                ]
                self.assertEqual(persisted["category"], category)
                self.assertNotIn("errors", persisted)
                adapter.credential_binding_ids.unlink()

        missing_adapter = self._configured_adapter()
        missing_adapter.credential_binding_ids.unlink()
        missing_result = self._transport().verify_document_connection(
            self.document,
            credential_provider=credential_provider,
        )
        self.assertEqual(missing_result["category"], "credential_absent")
        credential_provider.resolve.assert_not_called()

        expired_adapter = self._configured_adapter()
        self.credential.not_after = datetime(2020, 1, 1)
        expired_result = self._transport().verify_document_connection(
            self.document,
            credential_provider=credential_provider,
        )
        self.assertEqual(expired_result["category"], "certificate_expired")
        credential_provider.resolve.assert_not_called()
        expired_adapter.credential_binding_ids.unlink()

    def test_document_preflight_persists_only_safe_http_metadata(self):
        adapter = self._configured_adapter()
        credentials = SimpleNamespace(
            endpoint_url="https://sifen-test.example.test/de",
            timeout_seconds=7,
            mutual_tls_credential=self.credential,
        )
        provider = Mock()
        provider.resolve.return_value = credentials
        result = {
            "ok": True,
            "category": "http_response_received",
            "http_status": 405,
            "tls_handshake_succeeded": True,
            "message": "safe",
        }
        transport = self._transport()

        with patch.object(
            transport,
            "verify_connection",
            return_value=result,
        ):
            returned = transport.verify_document_connection(
                self.document,
                credential_provider=provider,
            )

        self.assertIs(returned, result)
        persisted = json.loads(adapter.metadata_json)[
            "sifen_test_mtls_preflight"
        ]
        self.assertEqual(
            set(persisted),
            {
                "ok",
                "category",
                "http_status",
                "client_certificate_configured",
                "server_certificate_verified",
                "tls_handshake_succeeded",
                "checked_at",
            },
        )
        self.assertTrue(persisted["ok"])
        self.assertEqual(persisted["http_status"], 405)
        self.assertNotIn(self.credential.secret_ref, adapter.metadata_json)

    def test_dns_failure_is_classified_for_submission(self):
        def urlopen(*args, **kwargs):
            raise error.URLError(socket.gaierror("dns secret detail"))

        with self.assertRaises(PySifenDnsError):
            self._transport(urlopen=urlopen)(
                endpoint_url="https://sifen-test.example.test/de",
                body=b"<soap/>",
                mutual_tls_credential=self.credential,
            )
