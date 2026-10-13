import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_module.services.account_move_integration import (
    FiscalDocumentFromAccountMoveService,
)
from odoo.addons.einvoice_py.services.py_account_move_integration_service import (
    PyFiscalDocumentFromAccountMoveService,
)
from odoo.addons.einvoice_py.services.py_kude_preview_service import PyKudePreviewService
from odoo.addons.einvoice_py.services.py_payload_builder import PyPayloadBuilder
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import PyUnsignedXmlBuilder
from odoo.addons.einvoice_py.services.py_sifen_submission_pipeline_service import (
    PySifenSubmissionPipelineService,
)


class _OfflineNceSubmission:
    def __init__(self):
        self.calls = []

    def submit_final_xml(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "outcome": "accepted",
            "authority_status_code": "0260",
            "authority_message": "Offline NCE validation only",
            "authority_receipt_ref": "OFFLINE-NCE",
            "request_hash": "1" * 64,
            "response_hash": "2" * 64,
            "http_status": 0,
            "duration_ms": 0,
            "metadata_json": {},
        }


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
        cls.credit_note_timbrado = cls.env["fiscal.py.timbrado"].create({
            "number": "4444444", "tenant_id": cls.tenant.id,
            "company_id": cls.company.id, "environment": "test",
            "document_type": "credit_note", "valid_from": date(2026, 1, 1),
            "allowed_point_of_issue_ids": [(6, 0, [cls.point.id])],
        })
        cls.credit_note_sequence = cls.env["fiscal.py.sequence"].create({
            "name": "Credit note sequence", "tenant_id": cls.tenant.id,
            "company_id": cls.company.id, "timbrado_id": cls.credit_note_timbrado.id,
            "establishment_id": cls.establishment.id, "point_of_issue_id": cls.point.id,
            "document_type": "credit_note", "next_number": 8000000, "padding": 7,
        })
        cls.debit_note_timbrado = cls.env["fiscal.py.timbrado"].create({
            "number": "4444444", "tenant_id": cls.tenant.id,
            "company_id": cls.company.id, "environment": "test",
            "document_type": "debit_note", "valid_from": date(2026, 1, 1),
            "allowed_point_of_issue_ids": [(6, 0, [cls.point.id])],
        })
        cls.debit_note_sequence = cls.env["fiscal.py.sequence"].create({
            "name": "Debit note sequence", "tenant_id": cls.tenant.id,
            "company_id": cls.company.id, "timbrado_id": cls.debit_note_timbrado.id,
            "establishment_id": cls.establishment.id, "point_of_issue_id": cls.point.id,
            "document_type": "debit_note", "next_number": 7000000, "padding": 7,
        })
        cls.self_invoice_timbrado = cls.env["fiscal.py.timbrado"].create({
            "number": "4444444", "tenant_id": cls.tenant.id,
            "company_id": cls.company.id, "environment": "test",
            "document_type": "self_invoice", "valid_from": date(2026, 1, 1),
            "allowed_point_of_issue_ids": [(6, 0, [cls.point.id])],
        })
        cls.self_invoice_sequence = cls.env["fiscal.py.sequence"].create({
            "name": "Self-invoice sequence", "tenant_id": cls.tenant.id,
            "company_id": cls.company.id, "timbrado_id": cls.self_invoice_timbrado.id,
            "establishment_id": cls.establishment.id, "point_of_issue_id": cls.point.id,
            "document_type": "self_invoice", "next_number": 6000000, "padding": 7,
        })
        cls.company.partner_id.write({
            "vat": "4444444-0", "country_id": cls.env.ref("base.py").id,
            "street": "Buyer address", "phone": "021000000", "email": "buyer@example.test",
            "py_sifen_receiver_profile": "taxpayer",
            "py_sifen_taxpayer_type": "2", "py_sifen_house_number": "1",
            "py_sifen_department_code": "11", "py_sifen_department_name": "CENTRAL",
            "py_sifen_district_code": "143", "py_sifen_district_name": "SAN LORENZO",
            "py_sifen_city_code": "3756", "py_sifen_city_name": "SAN LORENZO",
        })
        cls.tax_10 = cls._tax("IVA 10 explicit fixture", 10, "iva_10")
        cls.tax_5 = cls._tax("IVA 5 explicit fixture", 5, "iva_5")
        cls.tax_exempt = cls._tax("Exempt explicit fixture", 0, "exempt")
        cls.unmapped_tax = cls._tax("Unmapped 10 fixture", 10, False)
        cls.partner = cls.env["res.partner"].create({
            "name": "Offline Consumer", "py_sifen_receiver_profile": "unnamed_consumer",
            "country_id": cls.env.ref("base.py").id,
        })
        cls.three_installments = cls.env["account.payment.term"].create({
            "name": "Three monthly installments fixture",
            "line_ids": [
                (0, 0, {"value": "percent", "value_amount": 33, "nb_days": 30}),
                (0, 0, {"value": "percent", "value_amount": 33, "nb_days": 60}),
                (0, 0, {"value": "percent", "value_amount": 34, "nb_days": 90}),
            ],
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

    def _offline_signed_pipeline(self, document):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Offline credit fixture"),
        ])
        certificate = (
            x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(private_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(self.SNAPSHOT_TIME - timedelta(days=1))
            .not_valid_after(self.SNAPSHOT_TIME + timedelta(days=30))
            .sign(private_key=private_key, algorithm=hashes.SHA256())
        )
        submission = _OfflineNceSubmission()
        result = PySifenSubmissionPipelineService(
            self.env, submission_service=submission
        ).submit_test(
            document=document,
            payload=PyPayloadBuilder(self.env).build(document),
            signing_timestamp=self.SNAPSHOT_TIME,
            certificate_bytes=certificate.public_bytes(serialization.Encoding.PEM),
            private_key_bytes=private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            endpoint_url="https://offline.example.test/de",
            mutual_tls_credential={"offline": True},
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(submission.calls), 1)
        self.assertFalse(document.transmission_ids)

    def _move(
        self, taxes=None, *, partner=None, move_type="out_invoice", post=True,
        lines=None, reversed_entry=None, debit_origin=None, credit_note_reason=None,
        payment_term=None, sale_condition="1",
    ):
        taxes = taxes if taxes is not None else self.tax_10
        lines = lines or [("Service line", 110000, taxes)]
        values = {
            "move_type": move_type, "partner_id": (partner or self.partner).id,
            "invoice_date": date(2026, 8, 11), "currency_id": self.currency.id,
            "py_fiscal_tenant_id": self.tenant.id, "py_fiscal_environment": "test",
            "py_fiscal_establishment_id": self.establishment.id,
            "py_fiscal_point_of_issue_id": self.point.id,
            "reversed_entry_id": reversed_entry.id if reversed_entry else False,
            "debit_origin_id": debit_origin.id if debit_origin else False,
            "py_credit_note_reason_code": credit_note_reason,
            "invoice_payment_term_id": payment_term.id if payment_term else False,
            "py_sale_condition_code": sale_condition,
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

    def _business_partner(self):
        return self.env["res.partner"].create({
            "name": "Taxpayer Receiver", "vat": "80002201-7",
            "country_id": self.env.ref("base.py").id,
            "street": "Official address", "py_sifen_receiver_profile": "taxpayer",
            "py_sifen_taxpayer_type": "2", "py_sifen_house_number": "1",
            "py_sifen_department_code": "11", "py_sifen_department_name": "CENTRAL",
            "py_sifen_district_code": "143", "py_sifen_district_name": "SAN LORENZO",
            "py_sifen_city_code": "3756", "py_sifen_city_name": "SAN LORENZO",
        })

    def _accepted_invoice(self, *, amount=110000):
        partner = self._business_partner()
        move = self._move(partner=partner, lines=[("Original", amount, self.tax_10)])
        document = self.service.create(move=move)
        document.write({
            "state": "accepted",
            "authority_status": "0260",
            "authority_receipt_ref": "OFFLINE-PROTOCOL",
        })
        return move, document

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

    def test_general_entry_is_rejected(self):
        move = self._move(move_type="entry", post=False)
        with self.assertRaisesRegex(ValidationError, "vendor bills"):
            self.service.create(move=move)

    def _self_invoice_move(self, *, complete=True):
        seller = self.env["res.partner"].create({
            "name": "Rural non-taxpayer seller", "vat": "1234567",
            "country_id": self.env.ref("base.py").id, "street": "Seller address",
            "py_sifen_house_number": "0", "py_sifen_department_code": "11",
            "py_sifen_department_name": "CENTRAL", "py_sifen_city_code": "3756",
            "py_sifen_city_name": "SAN LORENZO",
            "py_sifen_self_invoice_seller_nature": "1",
            "py_sifen_self_invoice_id_type": "1",
        })
        move = self._move(move_type="in_invoice", partner=seller, post=False)
        if complete:
            move.write({
                "py_self_invoice_transaction_address": "Purchase location",
                "py_self_invoice_transaction_department_code": "11",
                "py_self_invoice_transaction_department_name": "CENTRAL",
                "py_self_invoice_transaction_city_code": "3756",
                "py_self_invoice_transaction_city_name": "SAN LORENZO",
            })
        move.action_post()
        return move

    def test_posted_vendor_bill_creates_schema_valid_self_invoice(self):
        move = self._self_invoice_move()
        document = self.service.create(move=move)
        payload = PyPayloadBuilder(self.env).build(document)
        xml_bytes = PyUnsignedXmlBuilder(self.env).build_from_payload(payload)
        from lxml import etree
        root = etree.fromstring(xml_bytes)
        ns = {"s": PyUnsignedXmlBuilder.SIFEN_NS}

        self.assertEqual(document.document_type, "self_invoice")
        self.assertEqual(document.account_move_id, move)
        self.assertEqual(document.py_cdc[:2], "04")
        self.assertEqual(document.py_seller_name, "Rural non-taxpayer seller")
        self.assertEqual(payload["self_invoice"]["seller_nature"], "1")
        self.assertEqual(root.xpath("string(.//s:gCamAE/s:dNumIDVen)", namespaces=ns), "1234567")
        self.assertEqual(root.xpath("string(.//s:gCamAE/s:dDirProv)", namespaces=ns), "Purchase location")
        self.assertEqual(len(root.xpath(".//s:gCamAE", namespaces=ns)), 1)
        self.assertEqual(self.service.create(move=move), document)

    def test_self_invoice_missing_seller_or_transaction_data_fails_closed(self):
        with self.assertRaisesRegex(ValidationError, "transaction address"):
            self.service.create(move=self._self_invoice_move(complete=False))

    def test_self_invoice_preview_and_full_signed_pipeline_are_offline(self):
        document = self.service.create(move=self._self_invoice_move())
        preview = PyKudePreviewService(self.env).render(document=document)
        self.assertTrue(preview.pdf_bytes.startswith(b"%PDF-"))
        self.assertEqual(preview.filename, f"PREVIEW-AFE-{document.py_full_number}.pdf")

        payload = PyPayloadBuilder(self.env).build(document)
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Offline AFE Fixture"),
        ])
        certificate = (
            x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(private_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(self.SNAPSHOT_TIME - timedelta(days=1))
            .not_valid_after(self.SNAPSHOT_TIME + timedelta(days=30))
            .sign(private_key=private_key, algorithm=hashes.SHA256())
        )
        submission = _OfflineNceSubmission()
        result = PySifenSubmissionPipelineService(
            self.env, submission_service=submission
        ).submit_test(
            document=document, payload=payload, signing_timestamp=self.SNAPSHOT_TIME,
            certificate_bytes=certificate.public_bytes(serialization.Encoding.PEM),
            private_key_bytes=private_key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            endpoint_url="https://offline.example.test/de",
            mutual_tls_credential={"offline": True},
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(submission.calls), 1)
        self.assertFalse(document.transmission_ids)

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
        business = self._business_partner()
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

    def test_credit_payment_term_is_snapshotted_as_schema_ordered_installments(self):
        move = self._move(
            lines=[("Credit service", 300000, self.tax_exempt)],
            payment_term=self.three_installments,
            sale_condition="2",
        )
        document = self.service.create(move=move)
        payload = PyPayloadBuilder(self.env).build(document)
        xml_bytes = PyUnsignedXmlBuilder(self.env).build_from_payload(payload)
        from lxml import etree
        root = etree.fromstring(xml_bytes)
        ns = {"s": PyUnsignedXmlBuilder.SIFEN_NS}
        installments = payload["condition"]["installments"]

        self.assertEqual(document.py_credit_condition_code, "2")
        self.assertEqual(document.py_installment_count, 3)
        self.assertEqual(len(installments), 3)
        self.assertEqual(sum(Decimal(item["amount"]) for item in installments), Decimal("300000.0"))
        self.assertEqual(root.xpath("string(.//s:gCamCond/s:iCondOpe)", namespaces=ns), "2")
        self.assertEqual(root.xpath("string(.//s:gPagCred/s:iCondCred)", namespaces=ns), "2")
        self.assertEqual(root.xpath("string(.//s:gPagCred/s:dCuotas)", namespaces=ns), "3")
        self.assertEqual(len(root.xpath(".//s:gPagCred/s:gCuotas", namespaces=ns)), 3)
        self.assertFalse(root.xpath(".//s:gCamCond/s:gPaConEIni", namespaces=ns))
        self._offline_signed_pipeline(document)

    def test_credit_payload_without_installment_snapshot_fails_closed(self):
        document = self.service.create(move=self._move())
        document.write({"py_sale_condition_code": "2", "py_installments_json": False})
        with self.assertRaisesRegex(ValidationError, "snapshot is required"):
            PyPayloadBuilder(self.env).build(document)

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

    def test_posted_refund_creates_nce_linked_to_accepted_invoice(self):
        original_move, original = self._accepted_invoice()
        refund = self._move(
            partner=original_move.partner_id,
            move_type="out_refund",
            reversed_entry=original_move,
            credit_note_reason="2",
            lines=[("Returned service", 55000, self.tax_10)],
        )

        note = self.service.create(move=refund)

        self.assertEqual(note.document_type, "credit_note")
        self.assertEqual(note.original_document_id, original)
        self.assertEqual(note.py_credit_debit_reason_code, "2")
        self.assertTrue(note.py_cdc.startswith("05"))
        self.assertEqual(note.py_timbrado_id, self.credit_note_timbrado)
        self.assertEqual(note.state, "ready")

        repeated = self.service.create(move=refund)
        self.assertEqual(repeated, note)
        self.assertEqual(
            self.env["fiscal.document"].search_count([
                ("account_move_id", "=", refund.id),
                ("document_type", "=", "credit_note"),
            ]),
            1,
        )

    def test_nce_requires_reversal_accepted_identified_original_and_reason(self):
        original_move, original = self._accepted_invoice()
        cases = (
            ({"reversed_entry": None, "credit_note_reason": "2"}, "created from an original"),
            ({"reversed_entry": original_move, "credit_note_reason": None}, "Select the SIFEN"),
        )
        for values, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValidationError, message):
                    self.service.create(move=self._move(
                        partner=original_move.partner_id,
                        move_type="out_refund",
                        lines=[("Return", 10000, self.tax_10)],
                        **values,
                    ))
        original.write({"state": "rejected"})
        with self.assertRaisesRegex(ValidationError, "must be accepted"):
            self.service.create(move=self._move(
                partner=original_move.partner_id, move_type="out_refund",
                reversed_entry=original_move, credit_note_reason="2",
                lines=[("Return", 10000, self.tax_10)],
            ))

    def test_nce_amount_cannot_exceed_original_or_cumulative_balance(self):
        original_move, original = self._accepted_invoice(amount=110000)
        first = self.service.create(move=self._move(
            partner=original_move.partner_id, move_type="out_refund",
            reversed_entry=original_move, credit_note_reason="2",
            lines=[("First return", 66000, self.tax_10)],
        ))
        self.assertEqual(first.original_document_id, original)
        with self.assertRaisesRegex(ValidationError, "remaining amount"):
            self.service.create(move=self._move(
                partner=original_move.partner_id, move_type="out_refund",
                reversed_entry=original_move, credit_note_reason="2",
                lines=[("Excess return", 55000, self.tax_10)],
            ))

    def test_nce_payload_and_xml_contain_reason_and_single_original_cdc(self):
        original_move, original = self._accepted_invoice()
        note = self.service.create(move=self._move(
            partner=original_move.partner_id, move_type="out_refund",
            reversed_entry=original_move, credit_note_reason="3",
            lines=[("Discount", 11000, self.tax_10)],
        ))

        payload = PyPayloadBuilder(self.env).build(note)
        xml_bytes = PyUnsignedXmlBuilder(self.env).build_from_payload(payload)
        from lxml import etree
        root = etree.fromstring(xml_bytes)
        ns = {"s": PyUnsignedXmlBuilder.SIFEN_NS}

        self.assertEqual(payload["credit_debit_note"]["reason_code"], "3")
        self.assertEqual(payload["associated_document"]["cdc"], original.py_cdc)
        self.assertEqual(root.xpath("string(.//s:gCamNCDE/s:iMotEmi)", namespaces=ns), "3")
        self.assertEqual(
            root.xpath("string(.//s:gCamDEAsoc/s:dCdCDERef)", namespaces=ns),
            original.py_cdc,
        )
        self.assertEqual(len(root.xpath(".//s:gCamDEAsoc", namespaces=ns)), 1)

    def test_nce_preview_is_offline_and_uses_nce_filename(self):
        original_move, _original = self._accepted_invoice()
        note = self.service.create(move=self._move(
            partner=original_move.partner_id, move_type="out_refund",
            reversed_entry=original_move, credit_note_reason="2",
            lines=[("Return", 11000, self.tax_10)],
        ))

        result = PyKudePreviewService(self.env).render(document=note)

        self.assertTrue(result.pdf_bytes.startswith(b"%PDF-"))
        self.assertEqual(result.filename, f"PREVIEW-NCE-{note.py_full_number}.pdf")
        self.assertFalse(note.transmission_ids)

    def test_posted_odoo_debit_note_creates_schema_valid_nde(self):
        original_move, original = self._accepted_invoice()
        debit_move = self._move(
            partner=original_move.partner_id,
            debit_origin=original_move,
            credit_note_reason="8",
            lines=[("Price adjustment", 11000, self.tax_10)],
        )

        note = self.service.create(move=debit_move)
        repeated = self.service.create(move=debit_move)
        payload = PyPayloadBuilder(self.env).build(note)
        xml_bytes = PyUnsignedXmlBuilder(self.env).build_from_payload(payload)
        from lxml import etree
        root = etree.fromstring(xml_bytes)
        ns = {"s": PyUnsignedXmlBuilder.SIFEN_NS}

        self.assertEqual(repeated, note)
        self.assertEqual(note.document_type, "debit_note")
        self.assertEqual(note.original_document_id, original)
        self.assertEqual(note.py_credit_debit_reason_code, "8")
        self.assertTrue(note.py_cdc.startswith("06"))
        self.assertEqual(note.py_timbrado_id, self.debit_note_timbrado)
        self.assertEqual(note.state, "ready")
        self.assertEqual(payload["associated_document"]["cdc"], original.py_cdc)
        self.assertEqual(root.xpath("string(.//s:gCamNCDE/s:iMotEmi)", namespaces=ns), "8")
        self.assertEqual(
            root.xpath("string(.//s:gCamDEAsoc/s:dCdCDERef)", namespaces=ns),
            original.py_cdc,
        )
        self.assertEqual(
            self.env["fiscal.document"].search_count([
                ("account_move_id", "=", debit_move.id),
                ("document_type", "=", "debit_note"),
            ]),
            1,
        )

    def test_nde_fails_closed_without_valid_original_reason_or_scope(self):
        original_move, original = self._accepted_invoice()
        with self.assertRaisesRegex(ValidationError, "requires its original"):
            FiscalDocumentFromAccountMoveService(self.env).create(
                move=self._move(
                    partner=original_move.partner_id,
                    lines=[("Adjustment", 11000, self.tax_10)],
                ),
                tenant=self.tenant,
                adapter_config=self.adapter,
                document_type="debit_note",
            )
        with self.assertRaisesRegex(ValidationError, "debit note reason"):
            self.service.create(move=self._move(
                partner=original_move.partner_id,
                debit_origin=original_move,
                lines=[("Adjustment", 11000, self.tax_10)],
            ))
        original.write({"state": "rejected"})
        with self.assertRaisesRegex(ValidationError, "must be accepted"):
            self.service.create(move=self._move(
                partner=original_move.partner_id,
                debit_origin=original_move,
                credit_note_reason="8",
                lines=[("Adjustment", 11000, self.tax_10)],
            ))

    def test_nde_preview_and_full_signed_v150_pipeline_are_offline(self):
        original_move, _original = self._accepted_invoice()
        note = self.service.create(move=self._move(
            partner=original_move.partner_id,
            debit_origin=original_move,
            credit_note_reason="8",
            lines=[("Price adjustment", 11000, self.tax_10)],
        ))
        preview = PyKudePreviewService(self.env).render(document=note)
        self.assertTrue(preview.pdf_bytes.startswith(b"%PDF-"))
        self.assertEqual(preview.filename, f"PREVIEW-NDE-{note.py_full_number}.pdf")

        payload = PyPayloadBuilder(self.env).build(note)
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Offline NDE Fixture"),
        ])
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(self.SNAPSHOT_TIME - timedelta(days=1))
            .not_valid_after(self.SNAPSHOT_TIME + timedelta(days=30))
            .sign(private_key=private_key, algorithm=hashes.SHA256())
        )
        submission = _OfflineNceSubmission()
        result = PySifenSubmissionPipelineService(
            self.env, submission_service=submission
        ).submit_test(
            document=note,
            payload=payload,
            signing_timestamp=self.SNAPSHOT_TIME,
            certificate_bytes=certificate.public_bytes(serialization.Encoding.PEM),
            private_key_bytes=private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            endpoint_url="https://offline.example.test/de",
            mutual_tls_credential={"offline": True},
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["submission_status"], "accepted")
        self.assertEqual(len(submission.calls), 1)
        self.assertFalse(note.transmission_ids)

    def test_nce_real_signing_qr_and_final_v150_xsd_pipeline_offline(self):
        original_move, _original = self._accepted_invoice()
        note = self.service.create(move=self._move(
            partner=original_move.partner_id, move_type="out_refund",
            reversed_entry=original_move, credit_note_reason="2",
            lines=[("Return", 11000, self.tax_10)],
        ))
        payload = PyPayloadBuilder(self.env).build(note)
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Offline NCE Fixture"),
        ])
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(self.SNAPSHOT_TIME - timedelta(days=1))
            .not_valid_after(self.SNAPSHOT_TIME + timedelta(days=30))
            .sign(private_key=private_key, algorithm=hashes.SHA256())
        )
        submission = _OfflineNceSubmission()

        result = PySifenSubmissionPipelineService(
            self.env, submission_service=submission
        ).submit_test(
            document=note,
            payload=payload,
            signing_timestamp=self.SNAPSHOT_TIME,
            certificate_bytes=certificate.public_bytes(serialization.Encoding.PEM),
            private_key_bytes=private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            endpoint_url="https://offline.example.test/de",
            mutual_tls_credential={"offline": True},
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["submission_status"], "accepted")
        self.assertEqual(result["authority_code"], "0260")
        self.assertTrue(result["final_xml_attachment_id"])
        self.assertEqual(len(submission.calls), 1)
        self.assertFalse(note.transmission_ids)
