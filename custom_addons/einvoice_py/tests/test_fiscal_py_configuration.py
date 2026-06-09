from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


class TestFiscalPyConfiguration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant_a = cls.env["fiscal.tenant"].create({
            "name": "Paraguay Tenant A",
            "code": "py-a",
            "company_id": cls.env.company.id,
        })
        cls.tenant_b = cls.env["fiscal.tenant"].create({
            "name": "Paraguay Tenant B",
            "code": "py-b",
            "company_id": cls.env.company.id,
        })
        cls.user_a = cls._create_user("py-user-a", cls.tenant_a)

    @classmethod
    def _create_user(cls, login, tenant):
        return cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": login,
            "login": login,
            "email": f"{login}@example.com",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
            "allowed_fiscal_tenant_ids": [(6, 0, [tenant.id])],
        })

    def _create_issuer(self, tenant=None, ruc="80012345", ruc_dv="6", environment="test"):
        tenant = tenant or self.tenant_a
        return self.env["fiscal.py.issuer"].sudo().create({
            "name": f"Issuer {tenant.code} {environment}",
            "tenant_id": tenant.id,
            "company_id": self.env.company.id,
            "environment": environment,
            "ruc": ruc,
            "ruc_dv": ruc_dv,
            "taxpayer_type": "2",
        })

    def _create_establishment(self, tenant=None, code="001"):
        tenant = tenant or self.tenant_a
        issuer = self.env["fiscal.py.issuer"].sudo().search(
            [
                ("tenant_id", "=", tenant.id),
                ("company_id", "=", self.env.company.id),
                ("environment", "=", "test"),
                ("active", "=", True),
            ],
            limit=1,
        ) or self._create_issuer(tenant)
        return self.env["fiscal.py.establishment"].sudo().create({
            "name": f"Establishment {code}",
            "code": code,
            "tenant_id": tenant.id,
            "company_id": self.env.company.id,
            "issuer_id": issuer.id,
        })

    def test_issuer_ruc_must_be_numeric_and_at_most_eight_digits(self):
        with self.assertRaises(ValidationError):
            self._create_issuer(ruc="800ABC")

        with self.assertRaises(ValidationError):
            self._create_issuer(ruc="123456789")

    def test_issuer_ruc_dv_must_be_one_digit(self):
        with self.assertRaises(ValidationError):
            self._create_issuer(ruc_dv="A")

        with self.assertRaises(ValidationError):
            self._create_issuer(ruc_dv="12")

    def test_only_one_active_issuer_per_tenant_company_environment(self):
        self._create_issuer()

        with self.assertRaises(ValidationError):
            self._create_issuer(ruc="80012346", ruc_dv="7")

    def test_active_establishment_requires_issuer(self):
        with self.assertRaises(ValidationError):
            self.env["fiscal.py.establishment"].sudo().create({
                "name": "Establishment Without Issuer",
                "code": "003",
                "tenant_id": self.tenant_a.id,
                "company_id": self.env.company.id,
            })

    def test_establishment_code_must_be_three_digits(self):
        with self.assertRaises(ValidationError):
            self._create_establishment(code="01")

        with self.assertRaises(ValidationError):
            self._create_establishment(code="ABC")

    def test_establishment_geography_fields_can_be_stored(self):
        establishment = self._create_establishment()

        establishment.write({
            "house_number": "123",
            "department_code": "1",
            "department_name": "CAPITAL",
            "district_code": "1",
            "district_name": "ASUNCION",
            "city_code": "1",
            "city_name": "ASUNCION",
            "branch_name": "CASA MATRIZ",
        })

        self.assertEqual(establishment.house_number, "123")
        self.assertEqual(establishment.department_code, "1")
        self.assertEqual(establishment.department_name, "CAPITAL")
        self.assertEqual(establishment.district_code, "1")
        self.assertEqual(establishment.district_name, "ASUNCION")
        self.assertEqual(establishment.city_code, "1")
        self.assertEqual(establishment.city_name, "ASUNCION")
        self.assertEqual(establishment.branch_name, "CASA MATRIZ")

    def test_economic_activity_can_be_created_and_displayed(self):
        issuer = self._create_issuer()

        activity = self.env["fiscal.py.economic.activity"].sudo().create({
            "issuer_id": issuer.id,
            "code": "620100",
            "description": "DESARROLLO DE SOFTWARE",
        })

        self.assertEqual(activity.tenant_id, issuer.tenant_id)
        self.assertEqual(activity.company_id, issuer.company_id)
        self.assertIn("620100", activity.display_name)
        self.assertIn("DESARROLLO DE SOFTWARE", activity.display_name)

    def test_duplicate_economic_activity_code_same_issuer_is_blocked(self):
        issuer = self._create_issuer()
        self.env["fiscal.py.economic.activity"].sudo().create({
            "issuer_id": issuer.id,
            "code": "620100",
            "description": "DESARROLLO DE SOFTWARE",
        })

        with mute_logger("odoo.sql_db"), self.env.cr.savepoint(), self.assertRaises(Exception):
            self.env["fiscal.py.economic.activity"].sudo().create({
                "issuer_id": issuer.id,
                "code": "620100",
                "description": "SERVICIOS INFORMATICOS",
            })

    def test_same_economic_activity_code_different_issuer_is_allowed(self):
        issuer_a = self._create_issuer(self.tenant_a, ruc="80012345", ruc_dv="6")
        issuer_b = self._create_issuer(self.tenant_b, ruc="80012346", ruc_dv="7")

        first = self.env["fiscal.py.economic.activity"].sudo().create({
            "issuer_id": issuer_a.id,
            "code": "620100",
            "description": "DESARROLLO DE SOFTWARE",
        })
        second = self.env["fiscal.py.economic.activity"].sudo().create({
            "issuer_id": issuer_b.id,
            "code": "620100",
            "description": "DESARROLLO DE SOFTWARE",
        })

        self.assertTrue(first)
        self.assertTrue(second)

    def test_issuer_has_economic_activity_lines(self):
        issuer = self._create_issuer()
        activity = self.env["fiscal.py.economic.activity"].sudo().create({
            "issuer_id": issuer.id,
            "code": "620100",
            "description": "DESARROLLO DE SOFTWARE",
        })

        self.assertIn(activity, issuer.economic_activity_ids)

    def test_point_of_issue_code_must_be_three_digits(self):
        establishment = self._create_establishment()

        with self.assertRaises(ValidationError):
            self.env["fiscal.py.point.of.issue"].sudo().create({
                "name": "Point 1",
                "code": "1",
                "establishment_id": establishment.id,
            })

    def test_timbrado_valid_to_must_not_precede_valid_from(self):
        with self.assertRaises(ValidationError):
            self.env["fiscal.py.timbrado"].sudo().create({
                "number": "12345678",
                "tenant_id": self.tenant_a.id,
                "company_id": self.env.company.id,
                "valid_from": "2026-06-02",
                "valid_to": "2026-06-01",
            })

    def test_tenant_isolation_record_rule(self):
        establishment_a = self._create_establishment(self.tenant_a, "001")
        establishment_b = self._create_establishment(self.tenant_b, "002")

        visible = self.env["fiscal.py.establishment"].with_user(self.user_a).search([
            ("id", "in", (establishment_a | establishment_b).ids),
        ])

        self.assertEqual(visible, establishment_a)

    def test_paraguay_records_use_business_display_names(self):
        establishment = self._create_establishment()
        point_of_issue = self.env["fiscal.py.point.of.issue"].sudo().create({
            "name": "Main Register",
            "code": "003",
            "establishment_id": establishment.id,
        })
        timbrado = self.env["fiscal.py.timbrado"].sudo().create({
            "number": "16056490",
            "tenant_id": self.tenant_a.id,
            "company_id": self.env.company.id,
            "environment": "test",
            "document_type": "invoice",
        })
        sequence = self.env["fiscal.py.sequence"].sudo().create({
            "name": "Invoice Sequence",
            "tenant_id": self.tenant_a.id,
            "company_id": self.env.company.id,
            "timbrado_id": timbrado.id,
            "establishment_id": establishment.id,
            "point_of_issue_id": point_of_issue.id,
            "document_type": "invoice",
            "next_number": 15,
        })

        self.assertIn("Timbrado 16056490", timbrado.display_name)
        self.assertIn("001-003", sequence.display_name)
        self.assertIn("Next 15", sequence.display_name)
