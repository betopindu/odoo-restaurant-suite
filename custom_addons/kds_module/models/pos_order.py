import json

from odoo import api, fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _get_kds_pos_line_key(self, pos_order, values):
        attribute_value_ids = values.get("attribute_value_ids") or []
        try:
            attribute_key = json.dumps(attribute_value_ids, sort_keys=True)
        except TypeError:
            attribute_key = str(attribute_value_ids)

        key_parts = [
            str(pos_order.id),
            str(values.get("product_id") or ""),
            values.get("name") or "",
            values.get("note") or "",
            attribute_key,
        ]
        return "|".join(key_parts)

    @api.model
    def create_from_ui(self, orders, draft=False):
        result = super().create_from_ui(orders, draft=draft)

        kitchen_order_model = self.env["kitchen.order"].sudo()
        kitchen_order_line_model = self.env["kitchen.order.line"].sudo()
        product_model = self.env["product.product"].sudo()
        pos_config_model = self.env["pos.config"].sudo()

        result_by_reference = {}
        for item in result:
            pos_reference = item.get("pos_reference")
            order_id = item.get("id")
            if pos_reference and order_id:
                result_by_reference[pos_reference] = order_id

        fallback_config = pos_config_model.search([], limit=1)

        for ui_order in orders:
            data = ui_order.get("data", {})
            pos_reference = data.get("name")

            if not pos_reference:
                continue

            order_id = result_by_reference.get(pos_reference)
            if not order_id:
                continue

            pos_order = self.browse(order_id).exists()
            if not pos_order:
                continue

            pos_config = pos_order.config_id or fallback_config
            table_name = pos_order.table_id.name if pos_order.table_id else "Sin mesa"

            try:
                preparation_change = json.loads(data.get("last_order_preparation_change") or "{}")
            except (TypeError, ValueError):
                continue

            if not isinstance(preparation_change, dict) or not preparation_change:
                continue

            lines_by_key = {}
            for values in preparation_change.values():
                if not isinstance(values, dict):
                    continue
                product_id = values.get("product_id")
                qty = values.get("quantity", 0.0) or 0.0
                note = values.get("note") or ""
                pos_line_key = self._get_kds_pos_line_key(pos_order, values)
                product = product_model.browse(product_id).exists() if product_id else False
                product_name = values.get("name") or (product.display_name if product else "Producto")

                if pos_line_key not in lines_by_key:
                    lines_by_key[pos_line_key] = {
                        "product": product,
                        "product_name": product_name,
                        "qty": 0.0,
                        "note": note,
                    }
                lines_by_key[pos_line_key]["qty"] += qty

            previous_sent_lines = kitchen_order_line_model.search([
                ("order_id.pos_order_id", "=", pos_order.id),
                ("pos_line_key", "!=", False),
            ])
            for pos_line_key in set(previous_sent_lines.mapped("pos_line_key")):
                if pos_line_key not in lines_by_key:
                    lines_by_key[pos_line_key] = {
                        "product": False,
                        "product_name": "",
                        "qty": 0.0,
                        "note": "",
                    }

            delta_lines = []
            cancellation_lines = []
            for pos_line_key, line_values in lines_by_key.items():
                previous_lines = kitchen_order_line_model.search([
                    ("order_id.pos_order_id", "=", pos_order.id),
                    ("pos_line_key", "=", pos_line_key),
                ])
                normal_qty = sum(previous_lines.filtered(lambda line: not line.is_cancellation).mapped("qty"))
                cancellation_qty = sum(previous_lines.filtered(lambda line: line.is_cancellation).mapped("qty"))
                already_sent_qty = normal_qty - cancellation_qty
                qty = line_values["qty"]
                delta_qty = qty - already_sent_qty

                if delta_qty == 0:
                    continue

                if delta_qty > 0:
                    delta_lines.append({
                        "pos_line_key": pos_line_key,
                        "pos_cumulative_qty": qty,
                        "qty": delta_qty,
                        "product": line_values["product"],
                        "product_name": line_values["product_name"],
                        "note": line_values["note"],
                    })
                    continue

                remaining_cancel_qty = abs(delta_qty)
                original_lines = kitchen_order_line_model.search([
                    ("order_id.pos_order_id", "=", pos_order.id),
                    ("pos_line_key", "=", pos_line_key),
                    ("is_cancellation", "=", False),
                    ("qty", ">", 0),
                ], order="created_at desc, id desc")

                for original_line in original_lines:
                    existing_cancel_lines = kitchen_order_line_model.search([
                        ("original_line_id", "=", original_line.id),
                        ("is_cancellation", "=", True),
                    ])
                    already_cancelled_qty = sum(existing_cancel_lines.mapped("qty"))
                    available_qty = original_line.qty - already_cancelled_qty
                    if available_qty <= 0:
                        continue

                    cancel_qty = min(remaining_cancel_qty, available_qty)
                    cancellation_lines.append({
                        "pos_line_key": pos_line_key,
                        "pos_cumulative_qty": qty,
                        "qty": cancel_qty,
                        "product": original_line.product_id,
                        "product_name": original_line.product_name,
                        "note": original_line.note,
                        "original_line": original_line,
                    })
                    remaining_cancel_qty -= cancel_qty
                    if remaining_cancel_qty <= 0:
                        break

            now = fields.Datetime.now()

            if delta_lines:
                kitchen_order = kitchen_order_model.create({
                    "pos_order_id": pos_order.id,
                    "pos_config_id": pos_config.id if pos_config else False,
                    "pos_reference": pos_order.pos_reference or pos_reference,
                    "table": table_name,
                    "created_at": now,
                    "last_activity_at": now,
                })

                for line_values in delta_lines:
                    kitchen_order_line_model.create({
                        "order_id": kitchen_order.id,
                        "product_id": line_values["product"].id if line_values["product"] else False,
                        "product_name": line_values["product_name"],
                        "qty": line_values["qty"],
                        "note": line_values["note"],
                        "pos_line_key": line_values["pos_line_key"],
                        "pos_cumulative_qty": line_values["pos_cumulative_qty"],
                        "state": "new",
                        "created_at": now,
                    })

            if cancellation_lines:
                reference_order = cancellation_lines[0]["original_line"].order_id
                change_order = kitchen_order_model.create({
                    "event_type": "change",
                    "change_reference_order_id": reference_order.id,
                    "pos_order_id": pos_order.id,
                    "pos_config_id": pos_config.id if pos_config else False,
                    "pos_reference": pos_order.pos_reference or pos_reference,
                    "table": table_name,
                    "created_at": now,
                    "last_activity_at": now,
                })

                for line_values in cancellation_lines:
                    kitchen_order_line_model.create({
                        "order_id": change_order.id,
                        "product_id": line_values["product"].id if line_values["product"] else False,
                        "product_name": line_values["product_name"],
                        "qty": line_values["qty"],
                        "note": line_values["note"],
                        "pos_line_key": line_values["pos_line_key"],
                        "pos_cumulative_qty": line_values["pos_cumulative_qty"],
                        "is_cancellation": True,
                        "original_line_id": line_values["original_line"].id,
                        "state": "new",
                        "created_at": now,
                    })

        return result
