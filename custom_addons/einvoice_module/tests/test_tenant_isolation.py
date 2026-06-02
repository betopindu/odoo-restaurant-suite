from odoo.tests.common import TransactionCase


class TestTenantIsolation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant_a = cls.env["fiscal.tenant"].create({
            "name": "Isolation Tenant A",
            "code": "iso-a",
            "company_id": cls.env.company.id,
        })
        cls.tenant_b = cls.env["fiscal.tenant"].create({
            "name": "Isolation Tenant B",
            "code": "iso-b",
            "company_id": cls.env.company.id,
        })
        cls.document_a = cls._create_document(cls.tenant_a, "tenant-a-document")
        cls.document_b = cls._create_document(cls.tenant_b, "tenant-b-document")
        cls.user_a = cls._create_user("fiscal-user-a", cls.tenant_a)
        cls.user_b = cls._create_user("fiscal-user-b", cls.tenant_b)
        cls.admin = cls.env.ref("base.user_admin")

    @classmethod
    def _create_document(cls, tenant, key):
        return cls.env["fiscal.document"].sudo().create({
            "name": key,
            "tenant_id": tenant.id,
            "company_id": cls.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "fake",
            "customer_name": "Test Customer",
            "amount_total": 100,
            "idempotency_key": key,
        })

    @classmethod
    def _create_user(cls, login, tenant):
        return cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": login,
            "login": login,
            "email": f"{login}@example.com",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
            "allowed_fiscal_tenant_ids": [(6, 0, [tenant.id])],
        })

    def _visible_documents(self, user):
        return self.env["fiscal.document"].with_user(user).search([
            ("id", "in", (self.document_a | self.document_b).ids),
        ])

    def test_user_a_sees_only_tenant_a_documents(self):
        self.assertEqual(self._visible_documents(self.user_a), self.document_a)

    def test_user_b_sees_only_tenant_b_documents(self):
        self.assertEqual(self._visible_documents(self.user_b), self.document_b)

    def test_admin_sees_all_tenant_documents(self):
        self.assertEqual(
            self._visible_documents(self.admin),
            self.document_a | self.document_b,
        )
