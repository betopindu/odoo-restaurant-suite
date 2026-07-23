import os
import tempfile
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_module.services.credential_provider import (
    FiscalCredentialProviderRegistry,
)
from odoo.addons.einvoice_module.services.pkcs12_material_provider import (
    ExternalSecretPkcs12MaterialProvider,
    FiscalCredentialMaterialLoadError,
)


class TestExternalSecretPkcs12MaterialProvider(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "PKCS#12 Provider Tenant",
            "code": "pkcs12-provider-tenant",
            "company_id": cls.company.id,
        })

    def _credential(self, **overrides):
        values = {
            "name": "External PKCS#12 Credential",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "provider_type": "external_secret",
            "material_format": "pkcs12",
            "secret_ref": "file:///unconfigured/credential.p12",
        }
        values.update(overrides)
        return self.env["fiscal.credential"].create(values)

    def _secret_file(self, contents):
        secret_file = tempfile.NamedTemporaryFile()
        secret_file.write(contents)
        secret_file.flush()
        self.addCleanup(secret_file.close)
        return secret_file

    def test_registry_returns_concrete_provider(self):
        provider = FiscalCredentialProviderRegistry(self.env).get_provider(
            self._credential()
        )

        self.assertIsInstance(provider, ExternalSecretPkcs12MaterialProvider)

    def test_loads_pkcs12_and_password_from_file_references(self):
        bundle = self._secret_file(b"synthetic-pkcs12")
        password = self._secret_file(b"safe-password\n")
        provider = ExternalSecretPkcs12MaterialProvider(self.env)

        material = provider.load_material(self._credential(
            secret_ref=f"file://{bundle.name}",
            password_secret_ref=f"file://{password.name}",
        ))

        self.assertEqual(material, {
            "pkcs12_bytes": b"synthetic-pkcs12",
            "password": b"safe-password",
        })

    def test_loads_password_from_environment_reference(self):
        bundle = self._secret_file(b"synthetic-pkcs12")
        provider = ExternalSecretPkcs12MaterialProvider(self.env)

        with patch.dict(os.environ, {"SIFEN_P12_PASSWORD": "safe-password"}):
            material = provider.load_material(self._credential(
                secret_ref=f"file://{bundle.name}",
                password_secret_ref="env://SIFEN_P12_PASSWORD",
            ))

        self.assertEqual(material["pkcs12_bytes"], b"synthetic-pkcs12")
        self.assertEqual(material["password"], b"safe-password")

    def test_password_is_optional(self):
        bundle = self._secret_file(b"synthetic-pkcs12")
        provider = ExternalSecretPkcs12MaterialProvider(self.env)

        material = provider.load_material(self._credential(
            secret_ref=f"file://{bundle.name}",
        ))

        self.assertIsNone(material["password"])

    def test_material_is_read_fresh_without_provider_cache(self):
        bundle = self._secret_file(b"first-pkcs12")
        provider = ExternalSecretPkcs12MaterialProvider(self.env)
        credential = self._credential(secret_ref=f"file://{bundle.name}")

        first = provider.load_material(credential)
        bundle.seek(0)
        bundle.write(b"second-pkcs12")
        bundle.truncate()
        bundle.flush()
        second = provider.load_material(credential)

        self.assertEqual(first["pkcs12_bytes"], b"first-pkcs12")
        self.assertEqual(second["pkcs12_bytes"], b"second-pkcs12")

    def test_missing_material_raises_safe_error(self):
        provider = ExternalSecretPkcs12MaterialProvider(self.env)

        with self.assertRaisesRegex(
            FiscalCredentialMaterialLoadError,
            "^External PKCS#12 credential material is unavailable\\.$",
        ) as raised:
            provider.load_material(self._credential())

        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("unconfigured", str(raised.exception))

    def test_missing_environment_password_raises_safe_error(self):
        bundle = self._secret_file(b"synthetic-pkcs12")
        provider = ExternalSecretPkcs12MaterialProvider(self.env)

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                FiscalCredentialMaterialLoadError,
                "^External PKCS#12 credential password is unavailable\\.$",
            ) as raised:
                provider.load_material(self._credential(
                    secret_ref=f"file://{bundle.name}",
                    password_secret_ref="env://MISSING_SIFEN_PASSWORD",
                ))

        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("MISSING_SIFEN_PASSWORD", str(raised.exception))

    def test_rejects_non_pkcs12_material(self):
        provider = ExternalSecretPkcs12MaterialProvider(self.env)

        with self.assertRaisesRegex(
            FiscalCredentialMaterialLoadError,
            "^External credential material must use PKCS#12 format\\.$",
        ):
            provider.load_material(self._credential(material_format="pem_pair"))

    def test_rejects_unsupported_secret_reference(self):
        provider = ExternalSecretPkcs12MaterialProvider(self.env)

        with self.assertRaisesRegex(
            FiscalCredentialMaterialLoadError,
            "^External PKCS#12 credential file reference is invalid\\.$",
        ):
            provider.load_material(self._credential(
                secret_ref="secret://tenant/certificate.p12",
            ))
