import ast
import json
import re
import threading
from pathlib import Path
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields, registry
from odoo.exceptions import AccessError, ValidationError
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
    def _preparation_payload(
        cls,
        reference,
        product,
        quantity,
        line_key="line-1",
        revision=None,
    ):
        payload = [{
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
        if revision is not None:
            payload[0]["data"]["kds_preparation_revision"] = revision
        return payload

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
        pos_order.last_order_preparation_change = payload[0]["data"]["last_order_preparation_change"]
        if "kds_preparation_revision" in payload[0]["data"]:
            pos_order.kds_preparation_revision = payload[0]["data"]["kds_preparation_revision"]
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
        self.assertEqual(
            self.env["kitchen.order.projection"].search_count([
                ("pos_order_id", "=", pos_order.id),
                ("state", "=", "complete"),
            ]),
            1,
        )

    def test_float_noise_does_not_create_delta(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-FLOAT")
        self._sync_kds(pos_order, self._preparation_payload(pos_order.pos_reference, self.product, 0.3))
        self._sync_kds(
            pos_order,
            self._preparation_payload(pos_order.pos_reference, self.product, 0.1 + 0.2),
        )
        self.assertEqual(len(self._kitchen_orders_for(pos_order).line_ids), 1)

    def test_failed_projection_rolls_back_partial_kds_and_is_recoverable(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-RECOVERY")
        payload = self._preparation_payload(pos_order.pos_reference, self.product, 2)
        pos_order.last_order_preparation_change = payload[0]["data"]["last_order_preparation_change"]
        projection_model = self.env["kitchen.order.projection"]
        original = type(self.env["kitchen.order.line"]).create

        def failing_create(self, vals_list):
            raise RuntimeError("injected line failure")

        try:
            type(self.env["kitchen.order.line"]).create = failing_create
            projection = projection_model.project_pos_order(pos_order)
        finally:
            type(self.env["kitchen.order.line"]).create = original

        self.assertEqual(projection.state, "failed")
        self.assertFalse(self._kitchen_orders_for(pos_order))
        projection.action_recover()
        self.assertEqual(projection.state, "complete")
        self.assertEqual(sum(self._kitchen_orders_for(pos_order).line_ids.mapped("qty")), 2)
        projection.action_recover()
        self.assertEqual(sum(self._kitchen_orders_for(pos_order).line_ids.mapped("qty")), 2)

    def test_stable_line_uuid_is_used_with_realistic_payload_key(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-UUID")
        payload = self._preparation_payload(pos_order.pos_reference, self.product, 1, "uuid-1 - ")
        values = json.loads(payload[0]["data"]["last_order_preparation_change"])
        values["uuid-1 - "]["line_uuid"] = "uuid-1"
        payload[0]["data"]["last_order_preparation_change"] = json.dumps(values)
        self._sync_kds(pos_order, payload)
        self.assertEqual(self._kitchen_orders_for(pos_order).line_ids.pos_line_key, f"{pos_order.id}|uuid-1")

    def test_real_create_from_ui_projects_persisted_restaurant_snapshot(self):
        session = self.env["pos.session"].create({
            "config_id": self.config.id,
            "user_id": self.env.user.id,
        })
        reference = "Order 00001-001-0001"
        snapshot = {
            "real-line-uuid - ": {
                "line_uuid": "real-line-uuid",
                "product_id": self.product.id,
                "name": self.product.display_name,
                "quantity": 1.5,
                "note": "",
                "attribute_value_ids": [],
            },
        }
        ui_order = {
            "id": "kds-real-ui",
            "to_invoice": False,
            "data": {
                "amount_paid": 0,
                "amount_return": 0,
                "amount_tax": 0,
                "amount_total": 15,
                "date_order": fields.Datetime.to_string(fields.Datetime.now()),
                "fiscal_position_id": False,
                "lines": [(0, 0, {
                    "discount": 0,
                    "id": "real-line-uuid",
                    "pack_lot_ids": [],
                    "price_unit": 10,
                    "product_id": self.product.id,
                    "price_subtotal": 15,
                    "price_subtotal_incl": 15,
                    "qty": 1.5,
                    "tax_ids": [(6, 0, [])],
                })],
                "name": reference,
                "partner_id": False,
                "pos_session_id": session.id,
                "sequence_number": 1,
                "statement_ids": [],
                "uid": "kds-real-ui",
                "user_id": self.env.uid,
                "last_order_preparation_change": json.dumps(snapshot),
                "kds_preparation_revision": 1,
            },
        }

        result = self.env["pos.order"].create_from_ui([ui_order], draft=True)

        pos_order = self.env["pos.order"].browse(result[0]["id"])
        self.assertEqual(json.loads(pos_order.last_order_preparation_change), snapshot)
        self.assertEqual(pos_order.kds_preparation_revision, 1)
        exported = self.env["pos.order"]._export_for_ui(pos_order)
        self.assertEqual(exported["kds_preparation_revision"], 1)
        self.assertEqual(sum(self._kitchen_orders_for(pos_order).line_ids.mapped("qty")), 1.5)

    def test_same_revision_different_snapshot_is_rejected_before_persistence(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-REV-CONFLICT")
        initial = self._preparation_payload(
            pos_order.pos_reference, self.product, 1, revision=1
        )[0]["data"]
        pos_order.write({
            "last_order_preparation_change": initial["last_order_preparation_change"],
            "kds_preparation_revision": 1,
        })
        conflicting = self._preparation_payload(
            pos_order.pos_reference, self.product, 2, revision=1
        )[0]["data"]

        with self.assertRaisesRegex(ValidationError, "different snapshots"):
            self.env["pos.order"]._process_order(
                {"data": conflicting}, draft=True, existing_order=pos_order
            )

        self.assertEqual(pos_order.kds_preparation_revision, 1)
        self.assertEqual(
            json.loads(pos_order.last_order_preparation_change)["line-1"]["quantity"],
            1,
        )

    def test_failure_after_one_line_rolls_back_entire_projection(self):
        product_b = self._create_product("KDS Failure Product B")
        pos_order = self._create_pos_order(self.config, "Order KDS-PARTIAL")
        payload = self._multi_line_payload(pos_order.pos_reference, self.product, product_b)
        pos_order.last_order_preparation_change = payload[0]["data"]["last_order_preparation_change"]
        line_class = type(self.env["kitchen.order.line"])
        original = line_class.create
        calls = {"count": 0}

        def fail_second_line(self, vals_list):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("injected failure after one KDS line")
            return original(self, vals_list)

        try:
            line_class.create = fail_second_line
            projection = self.env["kitchen.order.projection"].project_pos_order(pos_order)
        finally:
            line_class.create = original

        self.assertEqual(projection.state, "failed")
        self.assertFalse(self._kitchen_orders_for(pos_order))
        self.assertFalse(self.env["kitchen.order.line"].search([
            ("order_id.pos_order_id", "=", pos_order.id),
        ]))

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

    def test_repeated_state_new_revision_creates_cancellation_delta(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-A-B-A")

        self._sync_kds(
            pos_order,
            self._preparation_payload(
                pos_order.pos_reference, self.product, 1, revision=1
            ),
        )
        self._sync_kds(
            pos_order,
            self._preparation_payload(
                pos_order.pos_reference, self.product, 2, revision=2
            ),
        )
        third_event = self._preparation_payload(
            pos_order.pos_reference, self.product, 1, revision=3
        )
        self._sync_kds(pos_order, third_event)

        projections = self.env["kitchen.order.projection"].search([
            ("pos_order_id", "=", pos_order.id),
        ], order="source_revision")
        lines = self._kitchen_orders_for(pos_order).line_ids
        normal_lines = lines.filtered(lambda line: not line.is_cancellation)
        cancellation_lines = lines.filtered("is_cancellation")
        self.assertEqual(projections.mapped("source_revision"), [1, 2, 3])
        self.assertEqual(len(self._kitchen_orders_for(pos_order)), 3)
        self.assertEqual(normal_lines.mapped("qty"), [1, 1])
        self.assertEqual(cancellation_lines.mapped("qty"), [1])
        self.assertEqual(sum(normal_lines.mapped("qty")) - sum(cancellation_lines.mapped("qty")), 1)
        self.assertEqual(cancellation_lines.original_line_id, normal_lines[-1])

        self._sync_kds(pos_order, third_event)
        self.assertEqual(self.env["kitchen.order.projection"].search_count([
            ("pos_order_id", "=", pos_order.id),
        ]), 3)
        self.assertEqual(len(self._kitchen_orders_for(pos_order)), 3)

    def test_initial_revision_replay_and_reconnect_are_idempotent(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-REV-REPLAY")
        payload = self._preparation_payload(
            pos_order.pos_reference, self.product, 1, revision=1
        )

        self._sync_kds(pos_order, payload)
        self._sync_kds(pos_order, payload)
        self._sync_kds(pos_order, json.loads(json.dumps(payload)))

        self.assertEqual(self.env["kitchen.order.projection"].search_count([
            ("pos_order_id", "=", pos_order.id),
        ]), 1)
        self.assertEqual(len(self._kitchen_orders_for(pos_order)), 1)

    def test_distinct_revisions_preserve_identical_source_hashes(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-SAME-HASH")
        first = self._preparation_payload(
            pos_order.pos_reference, self.product, 1, revision=1
        )
        second = self._preparation_payload(
            pos_order.pos_reference, self.product, 1, revision=2
        )

        self._sync_kds(pos_order, first)
        self._sync_kds(pos_order, second)

        projections = self.env["kitchen.order.projection"].search([
            ("pos_order_id", "=", pos_order.id),
        ], order="source_revision")
        self.assertEqual(projections.mapped("source_revision"), [1, 2])
        self.assertEqual(len(set(projections.mapped("source_hash"))), 1)
        self.assertEqual(len(self._kitchen_orders_for(pos_order)), 1)

    def test_projection_revision_cannot_regress(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-REV-ORDER")
        self._sync_kds(
            pos_order,
            self._preparation_payload(
                pos_order.pos_reference, self.product, 2, revision=2
            ),
        )
        pos_order.last_order_preparation_change = self._preparation_payload(
            pos_order.pos_reference, self.product, 1, revision=1
        )[0]["data"]["last_order_preparation_change"]
        pos_order.kds_preparation_revision = 1

        with self.assertRaisesRegex(ValueError, "cannot move backwards"):
            self.env["kitchen.order.projection"].project_pos_order(pos_order)

    def test_legacy_projection_remains_readable_and_hash_idempotent(self):
        pos_order = self._create_pos_order(self.config, "Order KDS-LEGACY")
        payload = self._preparation_payload(pos_order.pos_reference, self.product, 1)

        self._sync_kds(pos_order, payload)
        projection = self.env["kitchen.order.projection"].search([
            ("pos_order_id", "=", pos_order.id),
        ])
        self.assertFalse(projection.source_revision)

        self._sync_kds(pos_order, payload)
        self.assertEqual(self.env["kitchen.order.projection"].search_count([
            ("pos_order_id", "=", pos_order.id),
        ]), 1)

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
        self._csrf_token = None

    def _display(self, config):
        return self.url_open(
            f"/kitchen/display?db={get_db_name()}&config_id={config.id}",
            allow_redirects=False,
        )

    def _post_line_next(self, line, config):
        if not self._csrf_token:
            page = self._display(config)
            match = re.search(r"csrf_token:\s*[\"']([^\"']+)", page.text)
            self.assertTrue(match, "Odoo page must expose its CSRF token")
            self._csrf_token = match.group(1)
        return self.url_open(
            f"/kitchen/display/line/{line.id}/next?db={get_db_name()}&config_id={config.id}",
            data={"csrf_token": self._csrf_token},
            allow_redirects=False,
        )

    def test_mutation_without_csrf_is_rejected(self):
        response = self.url_open(
            f"/kitchen/display/line/{self.line_a.id}/next?db={get_db_name()}&config_id={self.config_a.id}",
            data={"missing_csrf": "1"},
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.line_a.state, "new")

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

        self.assertEqual(response.status_code, 403)

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

    def test_frozen_frontend_contract(self):
        module_root = Path(__file__).resolve().parents[1]
        css = (module_root / "static/src/css/kitchen.css").read_text()
        template = (module_root / "views/kitchen_display.xml").read_text()
        javascript = (module_root / "static/src/js/kitchen_display.js").read_text()
        revision_javascript = (
            module_root / "static/src/js/pos_preparation_revision.js"
        ).read_text()
        self.assertIn(".o_kitchen_display_column_new", css)
        self.assertIn("lane_preparing", template)
        self.assertIn("lane_ready", template)
        self.assertIn("lane_done", template)
        self.assertIn("Math.max(refreshSeconds, 3)", javascript)
        self.assertIn("setInterval(refreshGrid, kdsSettings.refresh)", javascript)
        self.assertIn("new AudioContext()", javascript)
        self.assertIn("csrf_token: odoo.csrf_token", javascript)
        self.assertIn("order.changesToOrder(cancelled)", revision_javascript)
        self.assertIn("super.sendOrderInPreparationUpdateLastChange", revision_javascript)
        self.assertIn("super.export_as_JSON", revision_javascript)
        self.assertNotIn("printChanges(", revision_javascript)

    def test_pos_revision_patch_is_loaded_by_the_real_pos_bundle(self):
        module_root = Path(__file__).resolve().parents[1]
        manifest = ast.literal_eval((module_root / "__manifest__.py").read_text())
        revision_patch = "kds_module/static/src/js/pos_preparation_revision.js"

        self.assertIn(revision_patch, manifest["assets"]["point_of_sale._assets_pos"])
        self.assertNotIn(revision_patch, manifest["assets"]["web.assets_frontend"])
        self.assertIn(
            "kds_module/static/src/js/kitchen_display.js",
            manifest["assets"]["web.assets_frontend"],
        )

    def test_ordinary_internal_user_has_no_kds_crud(self):
        group_user = self.env.ref("base.group_user")
        user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Ordinary KDS Test User",
            "login": "ordinary_kds_test_user",
            "company_id": self.env.company.id,
            "company_ids": [(6, 0, [self.env.company.id])],
            "groups_id": [(6, 0, [group_user.id])],
        })
        with self.assertRaises(AccessError):
            self.env["kitchen.order"].with_user(user).create({"table": "Denied"})

    def test_kds_manager_retains_administration_access(self):
        manager_group = self.env.ref("kds_module.group_kds_manager")
        manager = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "KDS Manager Test",
            "login": "kds_manager_test",
            "company_id": self.env.company.id,
            "company_ids": [(6, 0, [self.env.company.id])],
            "groups_id": [(6, 0, [manager_group.id])],
        })
        config = self.env["pos.config"].create({"name": "KDS Manager Config"})
        order = self.env["kitchen.order"].with_user(manager).create({
            "table": "Allowed",
            "pos_config_id": config.id,
        })
        self.assertTrue(order)

    def test_kds_operator_record_rules_isolate_companies(self):
        other_company = self.env["res.company"].create({"name": "KDS Isolated Company"})
        config = self.env["pos.config"].create({"name": "KDS Rule Config"})
        other_order = self.env["kitchen.order"].create({
            "pos_config_id": config.id,
            "table": "Other Company",
        })
        # Isolate the record-rule contract from POS journal setup in this unit
        # test; the controller tests cover real cross-company POS configs.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE kitchen_order SET company_id = %s WHERE id = %s",
            [other_company.id, other_order.id],
        )
        other_order.invalidate_recordset(["company_id"])
        operator = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "KDS Company Operator",
            "login": "kds_company_operator",
            "company_id": self.env.company.id,
            "company_ids": [(6, 0, [self.env.company.id])],
            "groups_id": [(6, 0, [self.env.ref("kds_module.group_kds_user").id])],
        })
        operator_orders = self.env["kitchen.order"].with_user(operator).with_context(
            allowed_company_ids=[self.env.company.id]
        )
        self.assertFalse(operator_orders.search([
            ("id", "=", other_order.id),
        ]))
        with self.assertRaises(AccessError):
            other_order.with_user(operator).with_context(
                allowed_company_ids=[self.env.company.id]
            ).write({"table": "Denied"})


@tagged("post_install", "-at_install")
class TestKdsConcurrentProjection(KdsTestMixin, TransactionCase):

    def test_two_database_transactions_project_same_snapshot_once(self):
        db_registry = registry(get_db_name())
        with db_registry.cursor() as setup_cr:
            setup_env = api.Environment(setup_cr, SUPERUSER_ID, {})
            config = setup_env["pos.config"].create({"name": "KDS Concurrent POS"})
            product = setup_env["product.product"].create({
                "name": "KDS Concurrent Product",
                "list_price": 10,
                "available_in_pos": True,
            })
            session = setup_env["pos.session"].create({
                "config_id": config.id,
                "user_id": SUPERUSER_ID,
            })
            snapshot = json.dumps({
                "line-1": {
                    "product_id": product.id,
                    "name": product.display_name,
                    "quantity": 2,
                    "note": "",
                    "attribute_value_ids": [],
                },
            })
            pos_order = setup_env["pos.order"].create({
                "name": "Order KDS-CONCURRENT",
                "pos_reference": "Order KDS-CONCURRENT",
                "session_id": session.id,
                "config_id": config.id,
                "company_id": config.company_id.id,
                "amount_total": 0,
                "amount_tax": 0,
                "amount_paid": 0,
                "amount_return": 0,
                "last_order_preparation_change": snapshot,
                "kds_preparation_revision": 1,
            })
            order_id = pos_order.id
            setup_cr.commit()

        barrier = threading.Barrier(2)
        errors = []

        def worker():
            try:
                with db_registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    barrier.wait(timeout=5)
                    env["kitchen.order.projection"].project_pos_order(
                        env["pos.order"].browse(order_id)
                    )
                    cr.commit()
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(errors)
        with db_registry.cursor() as check_cr:
            check_env = api.Environment(check_cr, SUPERUSER_ID, {})
            self.assertEqual(
                check_env["kitchen.order.projection"].search_count([
                ("pos_order_id", "=", order_id),
                ("state", "=", "complete"),
                ]),
                1,
            )
            lines = check_env["kitchen.order.line"].search([
                ("order_id.pos_order_id", "=", order_id),
            ])
            self.assertEqual(sum(lines.mapped("qty")), 2)
