from odoo import fields, models


class KitchenOrderLine(models.Model):
    _name = "kitchen.order.line"
    _description = "Kitchen Order Line"
    _order = "id asc"

    order_id = fields.Many2one(
        "kitchen.order",
        string="Orden de cocina",
        required=True,
        ondelete="cascade",
    )

    product_id = fields.Many2one("product.product", string="Producto (ref)")
    product_name = fields.Char(string="Producto", required=True)
    qty = fields.Float(string="Cantidad", default=1.0, required=True)
    note = fields.Char(string="Nota")
    pos_line_key = fields.Char(string="Clave línea POS", index=True, copy=False)
    pos_cumulative_qty = fields.Float(string="Cantidad acumulada POS", copy=False)

    state = fields.Selection(
        [
            ("new", "Nuevo"),
            ("preparing", "Preparando"),
            ("ready", "Listo"),
            ("done", "Entregado"),
        ],
        string="Estado",
        default="new",
        required=True,
    )

    created_at = fields.Datetime(string="Creado", default=fields.Datetime.now, required=True)
    started_at = fields.Datetime(string="En preparación")
    ready_at = fields.Datetime(string="Listo")
    done_at = fields.Datetime(string="Entregado")

    def _touch_parent_order(self, now):
        for line in self:
            if line.order_id:
                line.order_id.last_activity_at = now
                line.order_id._update_admin_hidden_flags()

    def action_next_state(self):
        now = fields.Datetime.now()
        for line in self:
            if line.state == "new":
                line.write({
                    "state": "preparing",
                    "started_at": now,
                })
            elif line.state == "preparing":
                line.write({
                    "state": "ready",
                    "ready_at": now,
                })
            elif line.state == "ready":
                line.write({
                    "state": "done",
                    "done_at": now,
                })

        self._touch_parent_order(now)

    def action_set_state_new(self):
        now = fields.Datetime.now()
        for line in self:
            line.write({
                "state": "new",
                "started_at": False,
                "ready_at": False,
                "done_at": False,
            })
        self._touch_parent_order(now)

    def action_set_state_preparing(self):
        now = fields.Datetime.now()
        for line in self:
            line.write({
                "state": "preparing",
                "started_at": now,
                "ready_at": False,
                "done_at": False,
            })
        self._touch_parent_order(now)

    def action_set_state_ready(self):
        now = fields.Datetime.now()
        for line in self:
            vals = {
                "state": "ready",
                "ready_at": now,
                "done_at": False,
            }
            if not line.started_at:
                vals["started_at"] = now
            line.write(vals)
        self._touch_parent_order(now)

    def action_set_state_done(self):
        now = fields.Datetime.now()
        for line in self:
            vals = {
                "state": "done",
                "done_at": now,
            }
            if not line.started_at:
                vals["started_at"] = now
            if not line.ready_at:
                vals["ready_at"] = now
            line.write(vals)
        self._touch_parent_order(now)
