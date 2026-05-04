from odoo import api, fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

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

            kitchen_order = kitchen_order_model.create({
                "pos_order_id": pos_order.id,
                "pos_config_id": pos_config.id if pos_config else False,
                "pos_reference": pos_order.pos_reference or pos_reference,
                "table": table_name,
                "created_at": fields.Datetime.now(),
                "last_activity_at": fields.Datetime.now(),
            })

            raw_lines = data.get("lines", [])
            for raw_line in raw_lines:
                values = {}
                if isinstance(raw_line, (list, tuple)) and len(raw_line) >= 3 and isinstance(raw_line[2], dict):
                    values = raw_line[2]
                elif isinstance(raw_line, dict):
                    values = raw_line

                product_id = values.get("product_id")
                qty = values.get("qty", 1.0)
                note = values.get("note") or values.get("customer_note") or ""

                product = product_model.browse(product_id).exists() if product_id else False
                product_name = (
                    values.get("full_product_name")
                    or values.get("product_name")
                    or (product.display_name if product else "Producto")
                )

                kitchen_order_line_model.create({
                    "order_id": kitchen_order.id,
                    "product_id": product.id if product else False,
                    "product_name": product_name,
                    "qty": qty,
                    "note": note,
                    "state": "new",
                    "created_at": fields.Datetime.now(),
                })

        return result
