from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_module.services.credential_provider import (
    FiscalCredentialMaterialProvider,
    FiscalCredentialProviderRegistry,
)


class TestFiscalCredentials(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "Credential Tenant",
            "code": "credential-tenant",
            "company_id": cls.company.id,
        })
        cls.other_tenant = cls.env["fiscal.tenant"].create({
            "name": "Other Credential Tenant",
            "code": "other-credential-tenant",
            "company_id": cls.company.id,
        })
        cls.adapter = cls.env["fiscal.adapter.config"].create({
            "name": "Paraguay Test Adapter",
            "tenant_id": cls.tenant.id,
            "company_id": cls.company.id,
            "country_code": "PY",
            "adapter_code": "py",
            "environment": "test",
        })
        cls.ordinary_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create({
            "name": "Credential Ordinary User",
            "login": "credential-ordinary-user",
            "email": "credential-ordinary-user@example.com",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
            "allowed_fiscal_tenant_ids": [(6, 0, [cls.tenant.id])],
        })
        cls.admin = cls.env.ref("base.user_admin")

    def _credential(self, **overrides):
        values = {
            "name": "Paraguay Signing Credential",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "provider_type": "external_secret",
            "material_format": "pkcs12",
            "secret_ref": "secret://tenant/signing-certificate",
            "password_secret_ref": "secret://tenant/signing-password",
        }
        values.update(overrides)
        return self.env["fiscal.credential"].create(values)

    def test_credential_reference_can_be_created(self):
        credential = self._credential()

        self.assertEqual(credential.tenant_id, self.tenant)
        self.assertEqual(credential.provider_type, "external_secret")
        self.assertEqual(credential.material_format, "pkcs12")
        self.assertEqual(credential.inspection_status, "pending")

    def test_credential_model_has_no_secret_material_fields(self):
        fields = self.env["fiscal.credential"]._fields

        for forbidden_field in (
            "private_key",
            "private_key_bytes",
            "pkcs12_contents",
            "bundle_bytes",
            "pem_contents",
            "password",
        ):
            self.assertNotIn(forbidden_field, fields)

    def test_administrator_can_access_credential_records(self):
        credential = self._credential()

        visible = self.env["fiscal.credential"].with_user(self.admin).search([
            ("id", "=", credential.id),
        ])

        self.assertEqual(visible, credential)

    def test_ordinary_user_cannot_access_credential_records(self):
        credential = self._credential()

        with self.assertRaises(AccessError):
            self.env["fiscal.credential"].with_user(self.ordinary_user).search([
                ("id", "=", credential.id),
            ])

    def test_adapter_role_bindings_can_use_separate_credentials(self):
        signing = self._credential(name="Signing Credential")
        mutual_tls = self._credential(name="Mutual TLS Credential")

        signing_binding = self.env["fiscal.adapter.credential.binding"].create({
            "adapter_config_id": self.adapter.id,
            "credential_id": signing.id,
            "role": "xml_signing",
        })
        tls_binding = self.env["fiscal.adapter.credential.binding"].create({
            "adapter_config_id": self.adapter.id,
            "credential_id": mutual_tls.id,
            "role": "mutual_tls",
        })

        self.assertEqual(signing_binding.tenant_id, self.tenant)
        self.assertEqual(tls_binding.role, "mutual_tls")
        self.assertEqual(
            self.adapter.credential_binding_ids,
            signing_binding | tls_binding,
        )

    def test_duplicate_adapter_role_is_blocked(self):
        first = self._credential(name="First Signing Credential")
        second = self._credential(name="Second Signing Credential")
        self.env["fiscal.adapter.credential.binding"].create({
            "adapter_config_id": self.adapter.id,
            "credential_id": first.id,
            "role": "xml_signing",
        })

        with self.env.cr.savepoint():
            with self.assertRaises(IntegrityError):
                self.env["fiscal.adapter.credential.binding"].create({
                    "adapter_config_id": self.adapter.id,
                    "credential_id": second.id,
                    "role": "xml_signing",
                })

    def test_invalid_role_is_rejected(self):
        credential = self._credential()

        with self.assertRaises(ValueError):
            self.env["fiscal.adapter.credential.binding"].create({
                "adapter_config_id": self.adapter.id,
                "credential_id": credential.id,
                "role": "submission",
            })

    def test_pkcs11_provider_requires_pkcs11_material(self):
        with self.assertRaisesRegex(ValidationError, "must use the PKCS#11"):
            self._credential(
                provider_type="pkcs11",
                material_format="pkcs12",
            )

    def test_kms_provider_requires_provider_managed_material(self):
        with self.assertRaisesRegex(ValidationError, "provider-managed"):
            self._credential(
                provider_type="kms",
                material_format="pem_pair",
            )

    def test_cross_tenant_binding_is_blocked(self):
        credential = self._credential(
            name="Other Tenant Credential",
            tenant_id=self.other_tenant.id,
        )

        with self.assertRaisesRegex(ValidationError, "same tenant"):
            self.env["fiscal.adapter.credential.binding"].create({
                "adapter_config_id": self.adapter.id,
                "credential_id": credential.id,
                "role": "xml_signing",
            })

    def test_cross_company_binding_is_blocked(self):
        other_company = self.env["res.company"].create({"name": "Credential Company B"})
        credential = self._credential(
            name="Other Company Credential",
            company_id=other_company.id,
        )

        with self.assertRaisesRegex(ValidationError, "same company"):
            self.env["fiscal.adapter.credential.binding"].create({
                "adapter_config_id": self.adapter.id,
                "credential_id": credential.id,
                "role": "xml_signing",
            })

    def test_provider_base_is_abstract(self):
        provider = FiscalCredentialMaterialProvider(self.env)

        with self.assertRaises(NotImplementedError):
            provider.load_material(self._credential())

    def test_provider_registry_requires_registration(self):
        credential = self._credential(
            provider_type="kms",
            material_format="provider_managed",
        )
        registry = FiscalCredentialProviderRegistry(self.env)

        with self.assertRaisesRegex(LookupError, "No fiscal credential provider"):
            registry.get_provider(credential)

    def test_provider_registry_returns_registered_provider(self):
        class TestProvider(FiscalCredentialMaterialProvider):
            provider_type = "external_secret"

        FiscalCredentialProviderRegistry.register(TestProvider)
        self.addCleanup(
            FiscalCredentialProviderRegistry.unregister,
            TestProvider.provider_type,
        )

        provider = FiscalCredentialProviderRegistry(self.env).get_provider(
            self._credential()
        )

        self.assertIsInstance(provider, TestProvider)
        self.assertEqual(provider.env, self.env)
