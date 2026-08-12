import json
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase, get_db_name


class KdsTestMixin:

    @classmethod
    def _create_product(cls, name="KDS Test Product"):
        return cls.env["product.product"].create({
            "name": name,
            "list_price": 10.0,
            "available_in_pos": True,
        })

    @classmethod
    def _create_pos_config(cls, name, company=None, **extra):
        vals = {
            "name": name,
        }
        if company:
            vals["company_id"] = company.id
        vals.update(extra)
        return cls.env["pos.config"].create(vals)

    @classmethod
    def _create_pos_order(cls, config, reference):
        session = cls.env["pos.session"].create({
            "config_id": config.id,
            "user_id": cls.env.user.id,
        })
        return cls.env["pos.order"].create({
            "name": reference,
            "pos_reference": reference,
            "session_id": session.id,
            "config_id": config.id,
            "company_id": config.company_id.id,
            "amount_total": 0.0,
            "amount_tax": 0.0,
            "amount_paid": 0.0,
            "amount_return": 0.0,
        })

    @classmethod
    def _preparation_payload(cls, reference, product, quantity, line_key="line-1"):
        return [{
            "data": {
                "name": reference,
                "last_order_preparation_change": json.dumps({
                    line_key: {
                        "product_id": product.id,
                        "name": product.display_name,
                        "quantity": quantity,
                        "note": "",
                        "attribute_value_ids": [],
                    },
                }),
            },
        }]

    @classmethod
    def _multi_line_payload(cls, reference, product_a, product_b):
        return [{
            "data": {
                "name": reference,
                "last_order_preparation_change": json.dumps({
                    "line-1": {
                        "product_id": product_a.id,
                        "name": product_a.display_name,
                        "quantity": 1,
                        "note": "",
                        "attribute_value_ids": [],
                    },
                    "line-2": {
                        "product_id": product_b.id,
                        "name": product_b.display_name,
                        "quantity": 2,
                        "note": "",
                        "attribute_value_ids": [],
                    },
                }),
            },
        }]

    def _sync_kds(self, pos_order, payload):
        self.env["pos.order"]._sync_kds_from_ui_result(
            payload,
            [{"id": pos_order.id, "pos_reference": pos_order.pos_reference}],
        )

    def _kitchen_orders_for(self, pos_order):
        return self.env["kitchen.order"].search([
            ("pos_order_id", "=", pos_order.id),
        ], order="id asc")


@tagged("post_install", "-at_install")
class TestKdsCreateFromUiHardening(KdsTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls._create_pos_config("Existing Restaurant POS")
        cls.product = cls._create_product()

    def test_existing_pos_config_can_be_used(self):
        self.assertTrue(self.config)
        self.assertFalse(self.config.kds_show_done_lane)
        self.assertEqual(self.config.kds_refresh_seconds, 10)

    def test_restaurant_pos_order_creates_one_kitchen_order(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-001")

        self._sync_kds(
            pos_order,
            self._preparation_payload(pos_order.pos_reference, self.product, 2),
        )

        kitchen_orders = self._kitchen_orders_for(pos_order)
        self.assertEqual(len(kitchen_orders), 1)
        self.assertEqual(kitchen_orders.pos_config_id, self.config)
        self.assertEqual(kitchen_orders.line_ids.qty, 2)

    def test_multiple_order_lines_create_correct_kitchen_lines(self):
        product_b = self._create_product("KDS Test Product B")
        pos_order = self._create_pos_order(self.config, "Order KDS-002")

        self._sync_kds(
            pos_order,
            self._multi_line_payload(pos_order.pos_reference, self.product, product_b),
        )

        lines = self._kitchen_orders_for(pos_order).line_ids
        self.assertEqual(len(lines), 2)
        self.assertEqual(sum(lines.mapped("qty")), 3)

    def test_same_payload_resent_does_not_duplicate_kds_quantity(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-003")
        payload = self._preparation_payload(pos_order.pos_reference, self.product, 2)

        self._sync_kds(pos_order, payload)
        self._sync_kds(pos_order, payload)

        lines = self._kitchen_orders_for(pos_order).line_ids
        self.assertEqual(len(lines), 1)
        self.assertEqual(sum(lines.mapped("qty")), 2)

    def test_increased_cumulative_quantity_creates_only_delta(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-004")

        self._sync_kds(
            pos_order,
            self._preparation_payload(pos_order.pos_reference, self.product, 2),
        )
        self._sync_kds(
            pos_order,
            self._preparation_payload(pos_order.pos_reference, self.product, 5),
        )

        lines = self._kitchen_orders_for(pos_order).line_ids
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines.mapped("qty"), [2, 3])
        self.assertEqual(sum(lines.mapped("qty")), 5)

    def test_reduced_cumulative_quantity_creates_cancellation_delta(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-005")

        self._sync_kds(
            pos_order,
            self._preparation_payload(pos_order.pos_reference, self.product, 5),
        )
        self._sync_kds(
            pos_order,
            self._preparation_payload(pos_order.pos_reference, self.product, 2),
        )

        lines = self._kitchen_orders_for(pos_order).line_ids
        self.assertEqual(sum(lines.filtered(lambda line: not line.is_cancellation).mapped("qty")), 5)
        self.assertEqual(sum(lines.filtered("is_cancellation").mapped("qty")), 3)

    def test_payment_final_resend_does_not_duplicate_kitchen_order(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-006")
        payload = self._preparation_payload(pos_order.pos_reference, self.product, 1)

        self._sync_kds(pos_order, payload)
        pos_order.write({"amount_paid": 10.0})
        self._sync_kds(pos_order, payload)

        kitchen_orders = self._kitchen_orders_for(pos_order)
        self.assertEqual(len(kitchen_orders), 1)
        self.assertEqual(sum(kitchen_orders.line_ids.mapped("qty")), 1)

    def test_no_historical_backfill_occurs_automatically(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-HIST")

        self.assertFalse(self._kitchen_orders_for(pos_order))

    def test_create_from_ui_preserves_super_result_when_kds_sync_fails(self):
        pos_model = self.env["pos.order"]

        original = type(pos_model)._sync_kds_from_ui_result

        def failing_sync(self, orders, result):
            raise RuntimeError("isolated kds failure")

        try:
            type(pos_model)._sync_kds_from_ui_result = failing_sync
            with self.assertLogs(
                "odoo.addons.kds_module.models.pos_order",
                level="ERROR",
            ) as logs:
                result = pos_model.create_from_ui([])
        finally:
            type(pos_model)._sync_kds_from_ui_result = original

        self.assertEqual(result, [])
        self.assertIn("preserving POS create_from_ui result", "\n".join(logs.output))

    def test_cron_hides_only_eligible_historical_kds_records(self):
        old_done = self.env["kitchen.order"].create({
            "pos_config_id": self.config.id,
            "table": "1",
            "last_activity_at": fields.Datetime.now() - timedelta(hours=25),
        })
        self.env["kitchen.order.line"].create({
            "order_id": old_done.id,
            "product_name": "Done item",
            "qty": 1,
            "state": "done",
        })
        fresh = self.env["kitchen.order"].create({
            "pos_config_id": self.config.id,
            "table": "2",
            "last_activity_at": fields.Datetime.now(),
        })
        self.env["kitchen.order.line"].create({
            "order_id": fresh.id,
            "product_name": "Fresh item",
            "qty": 1,
            "state": "new",
        })

        self.env["kitchen.order"].cron_update_admin_hidden_orders()

        self.assertTrue(old_done.admin_hidden)
        self.assertFalse(fresh.admin_hidden)


@tagged("post_install", "-at_install")
class TestKdsHttpIsolation(KdsTestMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config_a = cls._create_pos_config("KDS Config A")
        cls.config_b = cls._create_pos_config("KDS Config B")
        cls.order_a = cls._create_kitchen_order(cls.config_a, "Mesa A", "Order A")
        cls.order_b = cls._create_kitchen_order(cls.config_b, "Mesa B", "Order B")
        cls.line_a = cls.order_a.line_ids[0]
        cls.line_b = cls.order_b.line_ids[0]

        cls.company_b = cls.env["res.company"].create({"name": "KDS Other Company"})
        group_user = cls.env.ref("base.group_user")
        cls.other_company_user = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "KDS Other Company User",
            "login": "kds_other_company_user",
            "password": "kds_other_company_user",
            "email": "kds_other_company_user@example.com",
            "company_id": cls.company_b.id,
            "company_ids": [(6, 0, [cls.company_b.id])],
            "groups_id": [(6, 0, [group_user.id])],
        })

    @classmethod
    def _create_kitchen_order(cls, config, table, reference, state="new"):
        order = cls.env["kitchen.order"].create({
            "pos_config_id": config.id,
            "pos_reference": reference,
            "table": table,
        })
        cls.env["kitchen.order.line"].create({
            "order_id": order.id,
            "product_name": f"Product {reference}",
            "qty": 1,
            "state": state,
        })
        return order

    def setUp(self):
        super().setUp()
        self.authenticate("admin", "admin")

    def _display(self, config):
        return self.url_open(
            f"/kitchen/display?db={get_db_name()}&config_id={config.id}",
            allow_redirects=False,
        )

    def _post_line_next(self, line, config):
        return self.url_open(
            f"/kitchen/display/line/{line.id}/next?db={get_db_name()}&config_id={config.id}",
            data="{}",
            headers={"Content-Type": "application/json"},
            allow_redirects=False,
        )

    def test_two_pos_configs_remain_isolated_in_display(self):
        response = self._display(self.config_a)
        body = response.text

        self.assertEqual(response.status_code, 200)
        self.assertIn("Mesa A", body)
        self.assertNotIn("Mesa B", body)

    def test_cross_config_line_mutation_is_rejected(self):
        response = self._post_line_next(self.line_b, self.config_a)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.line_b.state, "new")

    def test_cross_company_display_is_rejected(self):
        self.authenticate("kds_other_company_user", "kds_other_company_user")

        response = self.url_open(
            f"/kitchen/display?db={get_db_name()}&config_id={self.config_a.id}",
            allow_redirects=False,
        )

        self.assertEqual(response.status_code, 404)

    def test_new_preparing_ready_done_transitions(self):
        self.assertEqual(self.line_a.state, "new")

        self._post_line_next(self.line_a, self.config_a)
        self.line_a.invalidate_recordset()
        self.assertEqual(self.line_a.state, "preparing")
        self._post_line_next(self.line_a, self.config_a)
        self.line_a.invalidate_recordset()
        self.assertEqual(self.line_a.state, "ready")
        self._post_line_next(self.line_a, self.config_a)
        self.line_a.invalidate_recordset()
        self.assertEqual(self.line_a.state, "done")

    def test_delivered_lane_enabled_is_visible(self):
        self.config_a.kds_show_done_lane = True
        self.line_a.action_set_state_done()

        response = self._display(self.config_a)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Entregado", response.text)

    def test_delivered_lane_disabled_is_hidden(self):
        self.config_a.kds_show_done_lane = False
        self.line_a.action_set_state_done()

        response = self._display(self.config_a)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Entregado", response.text)

    def test_existing_pos_order_session_behavior_remains_valid(self):
        pos_order = self._create_pos_order(self.config_a, "Order Existing Session")

        self.assertEqual(pos_order.config_id, self.config_a)
        self.assertTrue(pos_order.session_id)


@tagged("post_install", "-at_install")
class TestKdsInstallMetadata(TransactionCase):

    def test_module_dependencies_are_pos_restaurant_only(self):
        module = self.env["ir.module.module"].search([
            ("name", "=", "kds_module"),
        ], limit=1)
        dependencies = set(module.dependencies_id.mapped("name"))

        self.assertIn("point_of_sale", dependencies)
        self.assertIn("pos_restaurant", dependencies)
        self.assertNotIn("einvoice_py", dependencies)
