from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestFiscalDocumentIdempotency(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant_a = cls.env["fiscal.tenant"].create({
            "name": "Idempotency Tenant A",
            "code": "idem-a",
            "company_id": cls.env.company.id,
        })
        cls.tenant_b = cls.env["fiscal.tenant"].create({
            "name": "Idempotency Tenant B",
            "code": "idem-b",
            "company_id": cls.env.company.id,
        })

    def _document_vals(self, tenant, key):
        return {
            "name": key,
            "tenant_id": tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "fake",
            "customer_name": "Test Customer",
            "amount_total": 100,
            "idempotency_key": key,
        }

    def test_duplicate_same_tenant_document_type_and_key_is_blocked(self):
        self.env["fiscal.document"].create(
            self._document_vals(self.tenant_a, "duplicate-key")
        )

        with self.assertRaises(ValidationError):
            self.env["fiscal.document"].create(
                self._document_vals(self.tenant_a, "duplicate-key")
            )

    def test_same_key_and_document_type_different_tenant_is_allowed(self):
        document_a = self.env["fiscal.document"].create(
            self._document_vals(self.tenant_a, "shared-key")
        )
        document_b = self.env["fiscal.document"].create(
            self._document_vals(self.tenant_b, "shared-key")
        )

        self.assertTrue(document_a)
        self.assertTrue(document_b)
        self.assertNotEqual(document_a.tenant_id, document_b.tenant_id)
