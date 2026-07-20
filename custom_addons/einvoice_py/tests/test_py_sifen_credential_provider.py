import json
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
    PySifenCredentialConfigurationError,
    PySifenCredentialMaterialError,
    PySifenCredentialProvider,
    PySifenCredentialScopeError,
)


class _Provider:
    def __init__(self, material=None, error=None):
        self.material = material
        self.error = error

    def load_material(self, credential):
        if self.error:
            raise self.error
        return self.material


class _Registry:
    def __init__(self, material=None, error=None):
        self.provider = _Provider(material=material, error=error)
        self.credentials = []

    def get_provider(self, credential):
        self.credentials.append(credential)
        return self.provider


class TestPySifenCredentialProvider(TransactionCase):
    RUC = "80012345"
    PASSWORD = b"signing-password-secret"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN Credential Provider Tenant",
            "code": "sifen-credential-provider",
            "company_id": cls.company.id,
        })

    def setUp(self):
        super().setUp()
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.certificate = self._certificate(self.key)
        self.adapter = self._adapter()
        self.csc = self.env["fiscal.py.csc"].create({
            "name": "SIFEN Credential CSC",
            "id_csc": "0001",
            "csc_value": "csc-value-secret",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "environment": "test",
        })
        self.document = self.env["fiscal.document"].create({
            "name": "SIFEN Credential Document",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py",
            "adapter_config_id": self.adapter.id,
            "customer_name": "Test Customer",
            "amount_total": 100,
            "idempotency_key": self.id(),
            "py_issuer_ruc": self.RUC,
            "py_csc_id": self.csc.id,
        })
        self.signing_credential = self._credential("Signing", "pem_pair")
        self.mtls_credential = self._credential("Mutual TLS", "pem_pair")
        self._bind("xml_signing", self.signing_credential)
        self._bind("mutual_tls", self.mtls_credential)

    def _adapter(self, **overrides):
        values = {
            "name": "Paraguay SIFEN Test",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "country_code": "PY",
            "adapter_code": "py",
            "environment": "test",
            "endpoint_base_url": "https://sifen-test.example.test/de",
            "timeout_seconds": 12,
        }
        values.update(overrides)
        return self.env["fiscal.adapter.config"].create(values)

    def _credential(self, name, material_format, **overrides):
        values = {
            "name": name,
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "provider_type": "external_secret",
            "material_format": material_format,
            "secret_ref": f"secret://test/{name}",
            "extracted_ruc": self.RUC,
        }
        values.update(overrides)
        return self.env["fiscal.credential"].create(values)

    def _bind(self, role, credential):
        return self.env["fiscal.adapter.credential.binding"].create({
            "adapter_config_id": self.adapter.id,
            "credential_id": credential.id,
            "role": role,
        })

    def _certificate(self, key):
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "SIFEN Fixture"),
        ])
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2026, 7, 1) - timedelta(days=1))
            .not_valid_after(datetime(2026, 7, 1) + timedelta(days=30))
            .sign(key, hashes.SHA256())
        )

    def _pem_material(self):
        return {
            "certificate_bytes": self.certificate.public_bytes(serialization.Encoding.PEM),
            "private_key_bytes": self.key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(self.PASSWORD),
            ),
            "password": self.PASSWORD,
        }

    def _resolve(self, material=None, error=None):
        registry = _Registry(material=material or self._pem_material(), error=error)
        result = PySifenCredentialProvider(
            self.env,
            provider_registry=registry,
        ).resolve(document=self.document)
        return result, registry

    def test_resolves_scoped_runtime_credentials_from_pem_material(self):
        result, registry = self._resolve()

        self.assertEqual(result.adapter_config, self.adapter)
        self.assertEqual(result.xml_signing_credential, self.signing_credential)
        self.assertEqual(result.mutual_tls_credential, self.mtls_credential)
        self.assertIn(b"BEGIN CERTIFICATE", result.signing_certificate_bytes)
        self.assertIn(b"BEGIN ENCRYPTED PRIVATE KEY", result.signing_private_key_bytes)
        self.assertEqual(result.signing_private_key_password, self.PASSWORD)
        self.assertEqual(result.csc_id, "0001")
        self.assertEqual(result.csc_value, "csc-value-secret")
        self.assertEqual(result.endpoint_url, "https://sifen-test.example.test/de")
        self.assertEqual(result.timeout_seconds, 12)
        self.assertEqual(registry.credentials, [self.signing_credential])

    def test_pkcs12_is_normalized_to_pem_bytes(self):
        self.signing_credential.material_format = "pkcs12"
        bundle = pkcs12.serialize_key_and_certificates(
            b"signing",
            self.key,
            self.certificate,
            None,
            serialization.BestAvailableEncryption(self.PASSWORD),
        )

        result, _registry = self._resolve({
            "pkcs12_bytes": bundle,
            "password": self.PASSWORD.decode(),
        })

        self.assertIn(b"BEGIN CERTIFICATE", result.signing_certificate_bytes)
        self.assertIn(b"BEGIN ENCRYPTED PRIVATE KEY", result.signing_private_key_bytes)
        self.assertEqual(result.signing_private_key_password, self.PASSWORD)

    def test_string_forms_are_fully_redacted(self):
        result, _registry = self._resolve()

        serialized = json.dumps({"repr": repr(result), "str": str(result)})
        self.assertEqual(str(result), "<PySifenRuntimeCredentials [REDACTED]>")
        self.assertNotIn("csc-value-secret", serialized)
        self.assertNotIn("signing-password-secret", serialized)
        self.assertNotIn("sifen-test.example.test", serialized)

    def test_missing_adapter_or_active_role_is_rejected(self):
        self.document.adapter_config_id = False
        with self.assertRaises(PySifenCredentialConfigurationError):
            self._resolve()

        self.document.adapter_config_id = self.adapter
        self.signing_credential.active = False
        with self.assertRaisesRegex(
            PySifenCredentialConfigurationError,
            "Exactly one active.*XML signing",
        ):
            self._resolve()

    def test_adapter_scope_and_credential_ruc_are_enforced(self):
        self.adapter.environment = "production"
        with self.assertRaises(PySifenCredentialScopeError):
            self._resolve()

        self.adapter.environment = "test"
        self.signing_credential.extracted_ruc = "99999999"
        with self.assertRaisesRegex(PySifenCredentialScopeError, "RUC"):
            self._resolve()

    def test_non_paraguay_document_is_rejected(self):
        self.document.country_code = "AR"

        with self.assertRaisesRegex(
            PySifenCredentialConfigurationError,
            "Paraguay document",
        ):
            self._resolve()

    def test_unsupported_material_format_is_rejected_before_provider_load(self):
        unsupported = self._credential(
            "KMS Signing",
            "provider_managed",
            provider_type="kms",
        )
        self.adapter.credential_binding_ids.filtered(
            lambda binding: binding.role == "xml_signing"
        ).credential_id = unsupported
        registry = _Registry(material={"secret": "must-not-load"})

        with self.assertRaisesRegex(
            PySifenCredentialConfigurationError,
            "unsupported",
        ):
            PySifenCredentialProvider(
                self.env,
                provider_registry=registry,
            ).resolve(document=self.document)

        self.assertEqual(registry.credentials, [])

    def test_unsupported_mutual_tls_format_is_rejected_without_loading_material(self):
        unsupported = self._credential(
            "KMS Mutual TLS",
            "provider_managed",
            provider_type="kms",
        )
        self.adapter.credential_binding_ids.filtered(
            lambda binding: binding.role == "mutual_tls"
        ).credential_id = unsupported
        registry = _Registry(material=self._pem_material())

        with self.assertRaisesRegex(
            PySifenCredentialConfigurationError,
            "unsupported",
        ):
            PySifenCredentialProvider(
                self.env,
                provider_registry=registry,
            ).resolve(document=self.document)

        self.assertEqual(registry.credentials, [])

    def test_provider_failure_and_bad_pkcs12_do_not_expose_secret_details(self):
        secret = "provider-internal-secret"
        with self.assertRaises(PySifenCredentialMaterialError) as raised:
            self._resolve(error=RuntimeError(secret))
        self.assertNotIn(secret, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

        self.signing_credential.material_format = "pkcs12"
        with self.assertRaises(PySifenCredentialMaterialError) as raised:
            self._resolve({"pkcs12_bytes": b"pkcs12-secret-invalid"})
        self.assertNotIn("pkcs12-secret-invalid", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_pem_certificate_and_private_key_must_be_bytes(self):
        unsafe_materials = [
            {
                "certificate_bytes": "certificate-text",
                "private_key_bytes": self._pem_material()["private_key_bytes"],
            },
            {
                "certificate_bytes": self._pem_material()["certificate_bytes"],
                "private_key_bytes": "private-key-text",
            },
        ]

        for material in unsafe_materials:
            with self.subTest(material_keys=sorted(material)):
                with self.assertRaisesRegex(
                    PySifenCredentialMaterialError,
                    "bytes",
                ):
                    self._resolve(material)

    def test_csc_endpoint_and_default_timeout_are_validated(self):
        self.csc.environment = "production"
        with self.assertRaises(PySifenCredentialScopeError):
            self._resolve()

        self.csc.environment = "test"
        self.adapter.endpoint_base_url = "https://user:secret@example.test/de?token=x"
        with self.assertRaises(PySifenCredentialConfigurationError) as raised:
            self._resolve()
        self.assertNotIn("secret", str(raised.exception))

        self.adapter.endpoint_base_url = "https://sifen-test.example.test/de"
        self.adapter.timeout_seconds = 0
        result, _registry = self._resolve()
        self.assertEqual(result.timeout_seconds, 30)
