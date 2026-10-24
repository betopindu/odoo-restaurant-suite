import ast
from pathlib import Path
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPosFiscalDecision(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "POS Fiscal Tenant",
            "company_id": cls.company.id,
        })
        cls.issuer = cls.env["fiscal.py.issuer"].create({
            "name": "POS Test Issuer",
            "tenant_id": cls.tenant.id,
            "company_id": cls.company.id,
            "environment": "test",
            "ruc": "80000000",
            "ruc_dv": "0",
            "taxpayer_type": "2",
        })
        cls.establishment = cls.env["fiscal.py.establishment"].create({
            "name": "POS Establishment",
            "code": "001",
            "tenant_id": cls.tenant.id,
            "company_id": cls.company.id,
            "issuer_id": cls.issuer.id,
        })
        cls.point = cls.env["fiscal.py.point.of.issue"].create({
            "name": "POS Point",
            "code": "001",
            "establishment_id": cls.establishment.id,
        })
        cls.unnamed = cls.env["res.partner"].create({
            "name": "POS Unnamed Consumer",
            "py_sifen_receiver_profile": "unnamed_consumer",
        })
        cls.taxpayer = cls.env["res.partner"].create({
            "name": "POS Taxpayer",
            "vat": "80000001-1",
            "py_sifen_receiver_profile": "taxpayer",
        })
        cls.cash_journal = cls.env["account.journal"].create({
            "name": "POS Fiscal Cash", "code": "PFCX", "type": "cash",
            "company_id": cls.company.id,
        })
        cls.bank_journal = cls.env["account.journal"].create({
            "name": "POS Fiscal Bank", "code": "PFBX", "type": "bank",
            "company_id": cls.company.id,
        })
        cls.cash_method = cls.env["pos.payment.method"].create({
            "name": "Fiscal Cash",
            "journal_id": cls.cash_journal.id,
            "company_id": cls.company.id,
            "py_sifen_payment_type_code": "1",
        })
        cls.qr_method = cls.env["pos.payment.method"].create({
            "name": "Fiscal QR",
            "journal_id": cls.bank_journal.id,
            "company_id": cls.company.id,
            "py_sifen_payment_type_code": "21",
        })
        cls.config = cls.env["pos.config"].create({
            "name": "Fiscal POS",
            "company_id": cls.company.id,
            "py_fiscal_checkout_enabled": True,
            "py_fiscal_allow_no_fe": True,
            "py_fiscal_environment": "test",
            "py_fiscal_tenant_id": cls.tenant.id,
            "py_fiscal_establishment_id": cls.establishment.id,
            "py_fiscal_point_of_issue_id": cls.point.id,
            "py_fiscal_unnamed_partner_id": cls.unnamed.id,
            "payment_method_ids": [(6, 0, [cls.cash_method.id, cls.qr_method.id])],
        })
        cls.session = cls.env["pos.session"].create({
            "config_id": cls.config.id,
            "user_id": cls.env.user.id,
        })

    def _data(self, **extra):
        values = {
            "user_id": self.env.uid,
            "pos_session_id": self.session.id,
            "lines": [],
            "name": "Order Fiscal-0001",
            "sequence_number": 1,
            "date_order": fields.Datetime.to_string(fields.Datetime.now()),
            "fiscal_position_id": False,
            "pricelist_id": False,
            "amount_paid": 0,
            "amount_total": 0,
            "amount_tax": 0,
            "amount_return": 0,
            "shipping_date": False,
            "py_fiscal_choice": "no_fe",
            "py_fiscal_decision_id": "decision-0001",
            "py_ruc_resolution": "not_applicable",
            "py_fiscal_delivery": "not_applicable",
            "to_invoice": False,
            "partner_id": False,
        }
        values.update(extra)
        return values

    def test_no_fe_is_explicit_and_does_not_request_invoice(self):
        self.assertTrue(self.env["pos.order"]._validate_py_fiscal_ui_order(self._data()))
        with self.assertRaisesRegex(ValidationError, "cannot request an Odoo invoice"):
            self.env["pos.order"]._validate_py_fiscal_ui_order(
                self._data(to_invoice=True)
            )

    def test_consumer_final_requires_configured_unnamed_partner(self):
        values = self._data(
            py_fiscal_choice="consumer_final",
            to_invoice=True,
            partner_id=self.unnamed.id,
            py_fiscal_delivery="print",
        )
        self.assertTrue(self.env["pos.order"]._validate_py_fiscal_ui_order(values))
        with self.assertRaisesRegex(ValidationError, "configured unnamed consumer"):
            self.env["pos.order"]._validate_py_fiscal_ui_order(
                dict(values, partner_id=self.taxpayer.id)
            )

    def test_with_ruc_requires_taxpayer_and_resolution_source(self):
        values = self._data(
            py_fiscal_choice="with_ruc",
            to_invoice=True,
            partner_id=self.taxpayer.id,
            py_ruc_resolution="local",
            py_fiscal_delivery="print",
        )
        self.assertTrue(self.env["pos.order"]._validate_py_fiscal_ui_order(values))
        with self.assertRaisesRegex(ValidationError, "resolution source"):
            self.env["pos.order"]._validate_py_fiscal_ui_order(
                dict(values, py_ruc_resolution=False)
            )

    def test_email_delivery_requires_address(self):
        values = self._data(
            py_fiscal_choice="consumer_final",
            to_invoice=True,
            partner_id=self.unnamed.id,
            py_fiscal_delivery="email",
            py_fiscal_email=False,
        )
        with self.assertRaisesRegex(ValidationError, "recipient email"):
            self.env["pos.order"]._validate_py_fiscal_ui_order(values)
        with self.assertRaisesRegex(ValidationError, "recipient email"):
            self.env["pos.order"]._validate_py_fiscal_ui_order(
                dict(values, py_fiscal_email="not-an-email")
            )

    def test_disabled_pos_rejects_fiscal_payload_but_normal_pos_remains_usable(self):
        config = self.env["pos.config"].create({"name": "Non Fiscal POS"})
        session = self.env["pos.session"].create({
            "config_id": config.id,
            "user_id": self.env.user.id,
        })
        with self.assertRaisesRegex(ValidationError, "disabled"):
            self.env["pos.order"]._validate_py_fiscal_ui_order(
                self._data(pos_session_id=session.id)
            )
        self.assertTrue(self.env["pos.order"]._validate_py_fiscal_ui_order({
            "pos_session_id": session.id,
        }))

    def test_confirmed_decision_is_immutable(self):
        order = self.env["pos.order"].create({
            "name": "Fiscal Order",
            "pos_reference": "Fiscal Order",
            "session_id": self.session.id,
            "config_id": self.config.id,
            "company_id": self.company.id,
            "amount_total": 0,
            "amount_tax": 0,
            "amount_paid": 0,
            "amount_return": 0,
            "py_fiscal_choice": "no_fe",
            "py_fiscal_decision_id": "decision-immutable",
            "py_ruc_resolution": "not_applicable",
            "py_fiscal_delivery": "print",
        })
        order.state = "paid"
        order.write({"py_fiscal_choice": "no_fe"})
        with self.assertRaisesRegex(ValidationError, "immutable"):
            order.write({"py_fiscal_choice": "consumer_final"})

    def test_order_fields_and_export_preserve_channel_contract(self):
        values = self.env["pos.order"]._order_fields(self._data())
        self.assertEqual(values["py_fiscal_choice"], "no_fe")
        self.assertEqual(values["py_fiscal_decision_id"], "decision-0001")

    def test_paid_fiscal_order_prepares_document_from_native_invoice_once(self):
        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.taxpayer.id,
        })
        move.state = "posted"
        order = self.env["pos.order"].create({
            "name": "Fiscal preparation order",
            "pos_reference": "Fiscal preparation order",
            "session_id": self.session.id,
            "config_id": self.config.id,
            "company_id": self.company.id,
            "partner_id": self.taxpayer.id,
            "account_move": move.id,
            "amount_total": 100,
            "amount_tax": 0,
            "amount_paid": 100,
            "amount_return": 0,
            "py_fiscal_choice": "with_ruc",
            "py_fiscal_decision_id": "decision-prepare",
            "py_ruc_resolution": "local",
            "py_fiscal_delivery": "print",
        })
        self.env["pos.payment"].create({
            "pos_order_id": order.id,
            "payment_method_id": self.cash_method.id,
            "amount": 100,
        })
        with patch.object(
            __import__(
                "odoo.addons.einvoice_py_pos.models.pos_order",
                fromlist=["PyFiscalDocumentFromAccountMoveService"],
            ).PyFiscalDocumentFromAccountMoveService,
            "create",
        ) as create:
            self.env["pos.order"]._prepare_py_fiscal_documents([{"id": order.id}])
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["customer_email_override"], None)
        self.assertEqual(create.call_args.kwargs["email_delivery_policy"], "suppressed")
        self.assertEqual(create.call_args.kwargs["payment_snapshot"], [{
            "type_code": "1", "amount": "100.0", "currency": order.currency_id.name,
        }])
        self.assertEqual(move.py_fiscal_tenant_id, self.tenant)
        self.assertEqual(move.py_fiscal_establishment_id, self.establishment)
        self.assertEqual(move.py_fiscal_point_of_issue_id, self.point)
        self.assertEqual(move.py_sale_condition_code, "1")

    def test_email_choice_is_snapshotted_for_automatic_delivery(self):
        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.taxpayer.id,
        })
        move.state = "posted"
        order = self.env["pos.order"].create({
            "name": "Fiscal email order",
            "pos_reference": "Fiscal email order",
            "session_id": self.session.id,
            "config_id": self.config.id,
            "company_id": self.company.id,
            "partner_id": self.taxpayer.id,
            "account_move": move.id,
            "amount_total": 100,
            "amount_tax": 0,
            "amount_paid": 100,
            "amount_return": 0,
            "py_fiscal_choice": "with_ruc",
            "py_fiscal_decision_id": "decision-email",
            "py_ruc_resolution": "local",
            "py_fiscal_delivery": "email",
            "py_fiscal_email": " checkout@example.test ",
        })
        self.env["pos.payment"].create({
            "pos_order_id": order.id,
            "payment_method_id": self.qr_method.id,
            "amount": 100,
        })
        with patch.object(
            __import__(
                "odoo.addons.einvoice_py_pos.models.pos_order",
                fromlist=["PyFiscalDocumentFromAccountMoveService"],
            ).PyFiscalDocumentFromAccountMoveService,
            "create",
        ) as create:
            self.env["pos.order"]._prepare_py_fiscal_documents([{"id": order.id}])

        create.assert_called_once()
        self.assertEqual(
            create.call_args.kwargs["customer_email_override"],
            "checkout@example.test",
        )
        self.assertEqual(create.call_args.kwargs["email_delivery_policy"], "requested")
        self.assertEqual(create.call_args.kwargs["payment_snapshot"][0]["type_code"], "21")

    def test_mixed_payment_snapshot_nets_cash_change_and_preserves_tenders(self):
        order = self.env["pos.order"].create({
            "name": "Mixed fiscal payment",
            "pos_reference": "Mixed fiscal payment",
            "session_id": self.session.id,
            "config_id": self.config.id,
            "company_id": self.company.id,
            "amount_total": 150,
            "amount_tax": 0,
            "amount_paid": 150,
            "amount_return": 50,
        })
        self.env["pos.payment"].create([
            {"pos_order_id": order.id, "payment_method_id": self.cash_method.id, "amount": 100},
            {"pos_order_id": order.id, "payment_method_id": self.qr_method.id, "amount": 100},
            {"pos_order_id": order.id, "payment_method_id": self.cash_method.id, "amount": -50, "is_change": True},
        ])

        snapshot = self.env["pos.order"]._py_sifen_payment_snapshot(order)

        self.assertEqual(snapshot, [
            {"type_code": "1", "amount": "50.0", "currency": order.currency_id.name},
            {"type_code": "21", "amount": "100.0", "currency": order.currency_id.name},
        ])

    def test_no_fe_order_never_prepares_fiscal_document(self):
        order = self.env["pos.order"].create({
            "name": "Non fiscal order",
            "pos_reference": "Non fiscal order",
            "session_id": self.session.id,
            "config_id": self.config.id,
            "company_id": self.company.id,
            "amount_total": 0,
            "amount_tax": 0,
            "amount_paid": 0,
            "amount_return": 0,
            "py_fiscal_choice": "no_fe",
            "py_fiscal_decision_id": "decision-no-fe",
            "py_ruc_resolution": "not_applicable",
            "py_fiscal_delivery": "not_applicable",
        })
        with patch.object(
            __import__(
                "odoo.addons.einvoice_py_pos.models.pos_order",
                fromlist=["PyFiscalDocumentFromAccountMoveService"],
            ).PyFiscalDocumentFromAccountMoveService,
            "create",
        ) as create:
            self.env["pos.order"]._prepare_py_fiscal_documents([{"id": order.id}])
        create.assert_not_called()

    def test_pos_loader_includes_fiscal_partner_fields_and_unnamed_partner(self):
        params = self.session._loader_params_res_partner()
        self.assertIn("py_sifen_receiver_profile", params["search_params"]["fields"])
        self.assertIn("py_sifen_taxpayer_type", params["search_params"]["fields"])
        partners = self.session._get_pos_ui_res_partner(params)
        loaded = {partner["id"]: partner for partner in partners}
        self.assertIn(self.unnamed.id, loaded)
        self.assertEqual(
            loaded[self.unnamed.id]["py_sifen_receiver_profile"],
            "unnamed_consumer",
        )

    def test_frontend_contract_only_calls_ruc_resolution_routes(self):
        module_root = Path(__file__).resolve().parents[1]
        manifest = ast.literal_eval((module_root / "__manifest__.py").read_text())
        assets = manifest["assets"]["point_of_sale._assets_pos"]
        self.assertIn(
            "einvoice_py_pos/static/src/js/pos_fiscal_checkout.js",
            assets,
        )
        self.assertIn(
            "einvoice_py_pos/static/src/xml/pos_fiscal_checkout.xml",
            assets,
        )
        javascript = (
            module_root / "static/src/js/pos_fiscal_checkout.js"
        ).read_text()
        template = (
            module_root / "static/src/xml/pos_fiscal_checkout.xml"
        ).read_text()
        self.assertIn("super.validateOrder(...arguments)", javascript)
        self.assertIn("super.export_as_JSON(...arguments)", javascript)
        self.assertIn("SelectionPopup", javascript)
        self.assertIn("py_fiscal_checkout_enabled", template)
        self.assertIn("selectPyFiscalChoice", template)
        self.assertIn('/einvoice_py_pos/ruc/resolve', javascript)
        self.assertIn('/einvoice_py_pos/ruc/manual', javascript)
        self.assertIn('/einvoice_py_pos/fiscal/status', javascript)
        self.assertIn("ReceiptScreen.prototype", javascript)
        self.assertIn("Automatic retries are disabled.", template)
        self.assertIn("aria-live=\"polite\"", template)
        self.assertIn(
            'import { jsonrpc } from "@web/core/network/rpc_service";',
            javascript,
        )
        self.assertIn(
            'jsonrpc("/einvoice_py_pos/ruc/resolve"',
            javascript,
        )
        self.assertIn("TextInputPopup", javascript)
        for forbidden in (
            'import { rpc } from "@web/core/network/rpc_service";',
            "orm.call",
            "fetch(",
            "XMLHttpRequest",
            "submit_and_persist",
            "Consulta DE",
        ):
            self.assertNotIn(forbidden, javascript)
