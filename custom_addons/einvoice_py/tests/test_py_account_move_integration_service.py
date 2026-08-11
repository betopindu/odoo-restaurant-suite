import json
from datetime import date, datetime

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_module.services.account_move_integration import (
    FiscalDocumentFromAccountMoveService,
)
from odoo.addons.einvoice_py.services.py_account_move_integration_service import (
    PyFiscalDocumentFromAccountMoveService,
)
from odoo.addons.einvoice_py.services.py_kude_preview_service import PyKudePreviewService


class TestPyAccountMoveIntegrationService(TransactionCase):
    SNAPSHOT_TIME = datetime(2026, 8, 11, 12, 0, 0)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.env["res.currency"].with_context(active_test=False).search(
            [("name", "=", "PYG")], limit=1
        )
        if not cls.currency:
            cls.currency = cls.env["res.currency"].create({
                "name": "PYG", "symbol": "Gs", "rounding": 1.0,
                "decimal_places": 0, "active": True,
            })
            cls.env["res.currency.rate"].create({
                "currency_id": cls.currency.id, "name": date.today(),
                "rate": 7000.0, "company_id": cls.company.id,
            })
        elif not cls.currency.active:
            cls.currency.active = True
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "Account Move Integration Tenant", "code": "move-integration",
            "company_id": cls.company.id,
        })
        cls.adapter = cls.env["fiscal.adapter.config"].create({
            "name": "Account Move SIFEN TEST", "tenant_id": cls.tenant.id,
            "company_id": cls.company.id, "country_code": "PY",
            "adapter_code": "py_sifen", "environment": "test",
        })
        cls.issuer = cls.env["fiscal.py.issuer"].create({
            "name": "Issuer Fixture", "tenant_id": cls.tenant.id,
            "company_id": cls.company.id, "environment": "test",
            "ruc": "4444444", "ruc_dv": "0", "taxpayer_type": "2",
        })
        cls.env["fiscal.py.economic.activity"].create({
            "issuer_id": cls.issuer.id, "code": "62090",
            "description": "Information technology services", "active": True,
        })
        cls.establishment = cls.env["fiscal.py.establishment"].create({
            "name": "MATRIZ", "branch_name": "MATRIZ", "code": "001",
            "tenant_id": cls.tenant.id, "company_id": cls.company.id,
            "issuer_id": cls.issuer.id, "address": "Fixture address",
            "house_number": "1", "department_code": "11", "department_name": "CENTRAL",
            "district_code": "143", "district_name": "SAN LORENZO",
            "city_code": "3756", "city_name": "SAN LORENZO",
        })
        cls.point = cls.env["fiscal.py.point.of.issue"].create({
            "name": "Point 001", "code": "001", "establishment_id": cls.establishment.id,
        })
        cls.timbrado = cls.env["fiscal.py.timbrado"].create({
            "number": "4444444", "tenant_id": cls.tenant.id,
            "company_id": cls.company.id, "environment": "test",
            "document_type": "invoice", "valid_from": date(2026, 1, 1),
            "allowed_point_of_issue_ids": [(6, 0, [cls.point.id])],
        })
        cls.csc = cls.env["fiscal.py.csc"].create({
            "name": "CSC fixture", "id_csc": "0001", "csc_value": "fixture-only-secret",
            "tenant_id": cls.tenant.id, "company_id": cls.company.id, "environment": "test",
        })
        cls.sequence = cls.env["fiscal.py.sequence"].create({
            "name": "Invoice sequence", "tenant_id": cls.tenant.id,
            "company_id": cls.company.id, "timbrado_id": cls.timbrado.id,
            "establishment_id": cls.establishment.id, "point_of_issue_id": cls.point.id,
            "document_type": "invoice", "next_number": 9000000, "padding": 7,
        })
        cls.tax_10 = cls._tax("IVA 10 explicit fixture", 10, "iva_10")
        cls.tax_5 = cls._tax("IVA 5 explicit fixture", 5, "iva_5")
        cls.tax_exempt = cls._tax("Exempt explicit fixture", 0, "exempt")
        cls.unmapped_tax = cls._tax("Unmapped 10 fixture", 10, False)
        cls.partner = cls.env["res.partner"].create({
            "name": "Offline Consumer", "py_sifen_receiver_profile": "unnamed_consumer",
            "country_id": cls.env.ref("base.py").id,
        })

    @classmethod
    def _tax(cls, name, amount, mapping):
        return cls.env["account.tax"].create({
            "name": name, "amount_type": "percent", "amount": amount,
            "type_tax_use": "sale", "price_include": True,
            "company_id": cls.company.id, "py_sifen_tax_treatment": mapping,
        })

    def setUp(self):
        super().setUp()
        self.service = PyFiscalDocumentFromAccountMoveService(
            self.env, snapshot_time_provider=lambda: self.SNAPSHOT_TIME
        )

    def _move(self, taxes=None, *, partner=None, move_type="out_invoice", post=True, lines=None):
        taxes = taxes if taxes is not None else self.tax_10
        lines = lines or [("Service line", 110000, taxes)]
        values = {
            "move_type": move_type, "partner_id": (partner or self.partner).id,
            "invoice_date": date(2026, 8, 11), "currency_id": self.currency.id,
            "py_fiscal_tenant_id": self.tenant.id, "py_fiscal_environment": "test",
            "py_fiscal_establishment_id": self.establishment.id,
            "py_fiscal_point_of_issue_id": self.point.id,
        }
        if move_type != "entry":
            values["invoice_line_ids"] = [(0, 0, {
                "name": name, "quantity": 1, "price_unit": price,
                "tax_ids": [(6, 0, tax_records.ids)],
            }) for name, price, tax_records in lines]
        move = self.env["account.move"].create(values)
        if post:
            move.action_post()
        return move

    def test_valid_posted_invoice_creates_ready_fiscal_snapshot(self):
        move = self._move()
        document = self.service.create(move=move)
        metadata = json.loads(document.metadata_json)

        self.assertEqual(document.account_move_id, move)
        self.assertEqual(document.source_model, "account.move")
        self.assertEqual(document.source_res_id, move.id)
        self.assertEqual(document.state, "ready")
        self.assertEqual(document.country_code, "PY")
        self.assertEqual(document.amount_total, move.amount_total)
        self.assertEqual(document.line_ids.source_line_id, move.invoice_line_ids.id)
        self.assertRegex(document.py_cdc, r"^\d{44}$")
        self.assertEqual(metadata["source"]["record_id"], move.id)
        self.assertEqual(len(metadata["snapshot_sha256"]), 64)

    def test_repeated_call_is_idempotent_and_consumes_one_number(self):
        move = self._move()
        before = self.sequence.next_number
        first = self.service.create(move=move)
        second = self.service.create(move=move)
        self.assertEqual(first, second)
        self.assertEqual(self.sequence.next_number, before + 1)
        self.assertEqual(move.fiscal_document_count, 1)

    def test_unique_database_invariant_covers_concurrent_creation(self):
        move = self._move()
        first = self.service.create(move=move)
        self.assertEqual(
            self.env["fiscal.document"].search_count([
                ("account_move_id", "=", move.id), ("adapter_config_id", "=", self.adapter.id),
            ]), 1,
        )
        self.assertEqual(self.service.create(move=move), first)

    def test_vendor_bill_and_general_entry_are_rejected(self):
        for move_type in ("in_invoice", "entry"):
            move = self._move(move_type=move_type, post=False)
            with self.assertRaisesRegex(ValidationError, "customer invoices"):
                self.service.create(move=move)

    def test_draft_and_cancelled_invoice_are_rejected(self):
        draft = self._move(post=False)
        with self.assertRaisesRegex(ValidationError, "posted"):
            self.service.create(move=draft)
        posted = self._move()
        posted.button_cancel()
        with self.assertRaisesRegex(ValidationError, "posted"):
            self.service.create(move=posted)

    def test_missing_or_wrong_scope_configuration_is_rejected(self):
        move = self._move()
        self.adapter.active = False
        with self.assertRaisesRegex(ValidationError, "adapter"):
            self.service.create(move=move)

    def test_explicit_tax_mappings_cover_10_5_exempt_and_mixed(self):
        move = self._move(lines=[
            ("Ten", 110000, self.tax_10),
            ("Five", 105000, self.tax_5),
            ("Exempt", 50000, self.tax_exempt),
        ])
        document = self.service.create(move=move)
        mapped = document.line_ids.sorted("sequence")
        self.assertEqual(mapped.mapped("py_tax_rate"), [10.0, 5.0, 0.0])
        self.assertEqual(mapped.mapped("py_tax_affectation"), ["1", "1", "3"])
        self.assertAlmostEqual(sum(mapped.mapped("total")), document.amount_total)

    def test_unmapped_multiple_and_tax_exclusive_configs_fail_closed(self):
        with self.assertRaisesRegex(ValidationError, "no explicit"):
            self.service.create(move=self._move(taxes=self.unmapped_tax))
        with self.assertRaisesRegex(ValidationError, "exactly one"):
            self.service.create(move=self._move(taxes=self.tax_10 | self.tax_5))
        exclusive = self._tax("Exclusive fixture", 10, "iva_10")
        exclusive.price_include = False
        with self.assertRaisesRegex(ValidationError, "tax-exclusive"):
            self.service.create(move=self._move(taxes=exclusive))

    def test_b2c_and_b2b_receiver_snapshots(self):
        b2c = self.service.create(move=self._move())
        self.assertEqual((b2c.py_receiver_nature, b2c.py_receiver_id_type), ("2", "5"))
        business = self.env["res.partner"].create({
            "name": "Taxpayer Receiver", "vat": "80002201-7", "country_id": self.env.ref("base.py").id,
            "street": "Official address", "py_sifen_receiver_profile": "taxpayer",
            "py_sifen_taxpayer_type": "2", "py_sifen_house_number": "1",
            "py_sifen_department_code": "11", "py_sifen_department_name": "CENTRAL",
            "py_sifen_district_code": "143", "py_sifen_district_name": "SAN LORENZO",
            "py_sifen_city_code": "3756", "py_sifen_city_name": "SAN LORENZO",
        })
        b2b = self.service.create(move=self._move(partner=business))
        self.assertEqual(b2b.customer_tax_id, "80002201-7")
        self.assertEqual((b2b.py_receiver_nature, b2b.py_receiver_operation_type), ("1", "1"))

    def test_missing_b2b_data_is_actionable(self):
        partner = self.env["res.partner"].create({
            "name": "Incomplete Taxpayer", "vat": "80002201-7",
            "country_id": self.env.ref("base.py").id,
            "py_sifen_receiver_profile": "taxpayer",
        })
        with self.assertRaisesRegex(ValidationError, "address.*department code"):
            self.service.create(move=self._move(partner=partner))

    def test_currency_and_totals_reconcile(self):
        move = self._move(lines=[("Ten", 110000, self.tax_10), ("Five", 52500, self.tax_5)])
        document = self.service.create(move=move)
        self.assertEqual(document.currency_id, move.currency_id)
        self.assertAlmostEqual(document.amount_untaxed, move.amount_untaxed)
        self.assertAlmostEqual(document.amount_tax, move.amount_tax)
        self.assertAlmostEqual(document.amount_total, move.amount_total)

    def test_cdc_date_uses_paraguay_civil_date_from_utc_snapshot(self):
        service = PyFiscalDocumentFromAccountMoveService(
            self.env,
            snapshot_time_provider=lambda: datetime(2026, 8, 11, 1, 0, 0),
        )
        document = service.create(move=self._move())
        self.assertIn("20260810", document.py_cdc_base)

    def test_preview_renders_without_authority_artifacts_or_transmission(self):
        document = self.service.create(move=self._move(lines=[
            ("Long description for the visible invoice preview wrapping", 110000, self.tax_10),
            ("Five percent", 52500, self.tax_5),
        ]))
        result = PyKudePreviewService(self.env).render(document=document)
        self.assertTrue(result.pdf_bytes.startswith(b"%PDF-"))
        self.assertEqual(result.filename, f"PREVIEW-FE-{document.py_full_number}.pdf")
        self.assertFalse(document.transmission_ids)
        self.assertFalse(document.attachment_ids.filtered(
            lambda item: item.attachment_type in ("paraguay_qr_payload", "paraguay_kude_pdf")
        ))

    def test_source_reset_and_cancel_are_blocked_after_snapshot(self):
        move = self._move()
        self.service.create(move=move)
        with self.assertRaisesRegex(ValidationError, "fiscal snapshot"):
            move.button_draft()
        with self.assertRaisesRegex(ValidationError, "fiscal snapshot"):
            move.button_cancel()
        with self.assertRaisesRegex(ValidationError, "fiscal snapshot"):
            move.write({"partner_id": self.env["res.partner"].create({"name": "Changed"}).id})

    def test_existing_api_created_document_remains_unlinked(self):
        document = self.env["fiscal.document"].create({
            "name": "API compatible", "tenant_id": self.tenant.id,
            "company_id": self.company.id, "document_type": "invoice",
            "country_code": "PY", "environment": "test", "adapter_code": "py_sifen",
            "customer_name": "API customer", "amount_total": 1,
            "idempotency_key": self.id(),
        })
        self.assertFalse(document.account_move_id)

    def test_neutral_service_rejects_company_scope_mismatch(self):
        move = self._move()
        other_company = self.env["res.company"].create({"name": "Other source company"})
        other_tenant = self.env["fiscal.tenant"].create({
            "name": "Other tenant", "company_id": other_company.id,
        })
        with self.assertRaisesRegex(ValidationError, "company"):
            FiscalDocumentFromAccountMoveService(self.env).create(
                move=move, tenant=other_tenant, adapter_config=self.adapter,
            )
