from datetime import datetime, timedelta, timezone

from odoo import api, fields, models


class KitchenOrder(models.Model):
    _name = "kitchen.order"
    _description = "Kitchen Order"
    _order = "admin_sort_rank asc, last_activity_at desc, created_at desc, id desc"

    name = fields.Char(string="Referencia", required=True, copy=False, default="/")
    event_type = fields.Selection(
        [
            ("normal", "Normal"),
            ("change", "Cambio"),
        ],
        string="Tipo de evento",
        default="normal",
        required=True,
        index=True,
    )
    change_reference_order_id = fields.Many2one(
        "kitchen.order",
        string="Orden de referencia",
        ondelete="set null",
    )
    pos_order_id = fields.Many2one("pos.order", string="Orden POS", ondelete="set null")
    pos_config_id = fields.Many2one("pos.config", string="Punto de Venta", ondelete="set null")
    pos_reference = fields.Char(string="Referencia POS")
    table = fields.Char(string="Mesa", required=True)
    created_at = fields.Datetime(string="Creado", default=fields.Datetime.now, required=True)
    last_activity_at = fields.Datetime(string="Última actividad", default=fields.Datetime.now, required=True)
    active = fields.Boolean(default=True)

    admin_hidden = fields.Boolean(
        string="Oculto en Cocina admin",
        default=False,
        copy=False,
        index=True,
    )

    line_ids = fields.One2many(
        "kitchen.order.line",
        "order_id",
        string="Líneas",
    )

    line_count = fields.Integer(
        string="Cantidad de ítems",
        compute="_compute_line_count",
        store=True,
    )

    lines_preview = fields.Text(
        string="Resumen de ítems",
        compute="_compute_lines_preview",
        store=True,
    )

    age_label = fields.Char(
        string="Tiempo transcurrido",
        compute="_compute_age_fields",
    )

    age_level = fields.Selection(
        [
            ("normal", "Normal"),
            ("warning", "Warning"),
            ("danger", "Danger"),
        ],
        string="Nivel de urgencia",
        compute="_compute_age_fields",
    )

    state_summary = fields.Selection(
        [
            ("new", "Nuevo"),
            ("preparing", "Preparando"),
            ("ready", "Listo"),
            ("done", "Entregado"),
            ("mixed", "Mixto"),
        ],
        string="Estado resumen",
        compute="_compute_state_summary",
        store=True,
    )

    admin_sort_rank = fields.Integer(
        string="Orden administrativo",
        compute="_compute_admin_sort_rank",
        store=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") in ("Nuevo", "/"):
                vals["name"] = seq.next_by_code("kitchen.order") or "/"
        orders = super().create(vals_list)
        orders._update_admin_hidden_flags()
        return orders

    @api.model
    def search(self, domain, offset=0, limit=None, order=None):
        if self.env.context.get("kds_refresh_admin_visibility"):
            self.sudo().with_context(kds_refresh_admin_visibility=False)._refresh_admin_hidden_before_search()
        return super().search(domain, offset=offset, limit=limit, order=order)

    def _refresh_admin_hidden_before_search(self):
        done_orders = self.with_context(kds_refresh_admin_visibility=False).search([
            ("state_summary", "=", "done")
        ])
        done_orders._update_admin_hidden_flags()

    @api.depends("line_ids.qty")
    def _compute_line_count(self):
        for order in self:
            order.line_count = len(order.line_ids.filtered(lambda l: l.qty > 0))

    @api.depends("line_ids.product_name", "line_ids.qty")
    def _compute_lines_preview(self):
        for order in self:
            parts = []
            for line in order.line_ids:
                if line.qty <= 0:
                    continue
                qty = int(line.qty) if line.qty == int(line.qty) else line.qty
                parts.append(f"{qty} x {line.product_name}")
            order.lines_preview = "\n".join(parts)

    @api.depends("line_ids.state", "line_ids.qty")
    def _compute_state_summary(self):
        for order in self:
            visible_lines = order.line_ids.filtered(lambda l: l.qty > 0)
            states = set(visible_lines.mapped("state"))

            if not states:
                order.state_summary = "new"
            elif len(states) == 1:
                order.state_summary = list(states)[0]
            else:
                order.state_summary = "mixed"

    @api.depends("state_summary")
    def _compute_admin_sort_rank(self):
        rank_map = {
            "mixed": 0,
            "new": 1,
            "preparing": 2,
            "ready": 3,
            "done": 4,
        }
        for order in self:
            order.admin_sort_rank = rank_map.get(order.state_summary or "new", 9)

    def _format_age(self, delta_seconds):
        minutes = int(delta_seconds // 60)
        hours = minutes // 60

        if minutes < 1:
            return "Hace menos de 1 min"
        if minutes < 60:
            return f"Hace {minutes} min"

        remaining_minutes = minutes % 60
        if remaining_minutes == 0:
            return f"Hace {hours} h"
        return f"Hace {hours} h {remaining_minutes} min"

    @api.depends(
        "created_at",
        "pos_config_id.kds_warning_minutes",
        "pos_config_id.kds_danger_minutes",
    )
    def _compute_age_fields(self):
        now = datetime.now(timezone.utc)

        for order in self:
            if not order.created_at:
                order.age_label = ""
                order.age_level = "normal"
                continue

            created = order.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)

            delta_seconds = max((now - created).total_seconds(), 0)
            minutes = delta_seconds / 60

            warning_minutes = order.pos_config_id.kds_warning_minutes or 5
            danger_minutes = order.pos_config_id.kds_danger_minutes or 10

            order.age_label = self._format_age(delta_seconds)

            if minutes >= danger_minutes:
                order.age_level = "danger"
            elif minutes >= warning_minutes:
                order.age_level = "warning"
            else:
                order.age_level = "normal"

    def _get_admin_done_visible_hours(self):
        self.ensure_one()

        if self.pos_config_id and self.pos_config_id.kds_admin_done_visible_hours:
            return self.pos_config_id.kds_admin_done_visible_hours

        global_config = self.env["pos.config"].sudo().search([], limit=1)
        return global_config.kds_admin_done_visible_hours or 24

    def _should_hide_in_admin(self):
        self.ensure_one()

        if self.state_summary != "done":
            return False

        if not self.last_activity_at:
            return False

        visible_hours = self._get_admin_done_visible_hours()
        if visible_hours <= 0:
            return False

        now = datetime.now(timezone.utc)
        activity_dt = self.last_activity_at
        if activity_dt.tzinfo is None:
            activity_dt = activity_dt.replace(tzinfo=timezone.utc)

        limit_dt = now - timedelta(hours=visible_hours)
        return activity_dt < limit_dt

    def _update_admin_hidden_flags(self):
        for order in self:
            order.admin_hidden = order._should_hide_in_admin()

    def action_move_lines_from_state(self, from_state):
        now = fields.Datetime.now()
        next_map = {
            "new": ("preparing", "started_at"),
            "preparing": ("ready", "ready_at"),
            "ready": ("done", "done_at"),
        }

        if from_state not in next_map:
            return

        next_state, date_field = next_map[from_state]

        for order in self:
            lines = order.line_ids.filtered(lambda l: l.state == from_state and l.qty > 0)
            if lines:
                if order.event_type == "change" and from_state == "new":
                    for line in lines:
                        vals = {
                            "state": "done",
                            "done_at": now,
                        }
                        if not line.started_at:
                            vals["started_at"] = now
                        if not line.ready_at:
                            vals["ready_at"] = now
                        line.write(vals)
                else:
                    vals = {
                        "state": next_state,
                        date_field: now,
                    }
                    lines.write(vals)
                order.last_activity_at = now
                order._update_admin_hidden_flags()

    def action_move_visible_lines_to_preparing(self):
        self.action_move_lines_from_state("new")

    def action_move_visible_lines_to_ready(self):
        self.action_move_lines_from_state("preparing")

    def action_move_visible_lines_to_done(self):
        self.action_move_lines_from_state("ready")

    def _get_visible_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(lambda l: l.qty > 0)

    def action_set_all_lines_new(self):
        now = fields.Datetime.now()
        for order in self:
            lines = order._get_visible_lines()
            if not lines:
                continue
            lines.write({
                "state": "new",
                "started_at": False,
                "ready_at": False,
                "done_at": False,
            })
            order.last_activity_at = now
            order._update_admin_hidden_flags()

    def action_set_all_lines_preparing(self):
        now = fields.Datetime.now()
        for order in self:
            lines = order._get_visible_lines()
            if not lines:
                continue
            lines.write({
                "state": "preparing",
                "started_at": now,
                "ready_at": False,
                "done_at": False,
            })
            order.last_activity_at = now
            order._update_admin_hidden_flags()

    def action_set_all_lines_ready(self):
        now = fields.Datetime.now()
        for order in self:
            lines = order._get_visible_lines()
            if not lines:
                continue
            for line in lines:
                vals = {
                    "state": "ready",
                    "ready_at": now,
                    "done_at": False,
                }
                if not line.started_at:
                    vals["started_at"] = now
                line.write(vals)
            order.last_activity_at = now
            order._update_admin_hidden_flags()

    def action_set_all_lines_done(self):
        now = fields.Datetime.now()
        for order in self:
            lines = order._get_visible_lines()
            if not lines:
                continue
            for line in lines:
                vals = {
                    "state": "done",
                    "done_at": now,
                }
                if not line.started_at:
                    vals["started_at"] = now
                if not line.ready_at:
                    vals["ready_at"] = now
                line.write(vals)
            order.last_activity_at = now
            order._update_admin_hidden_flags()

    def action_open_line_editor(self):
        self.ensure_one()
        title_parts = [self.name or "Orden"]
        if self.table:
            title_parts.append(f"Mesa {self.table}")
        if self.pos_reference:
            title_parts.append(self.pos_reference)

        return {
            "type": "ir.actions.act_window",
            "name": " · ".join(title_parts),
            "res_model": "kitchen.order.line",
            "view_mode": "kanban",
            "views": [
                (self.env.ref("kds_module.view_kitchen_order_line_editor_kanban").id, "kanban"),
            ],
            "target": "new",
            "domain": [
                ("order_id", "=", self.id),
                ("qty", ">", 0),
            ],
            "context": {
                "create": False,
                "edit": False,
                "delete": False,
            },
        }

    @api.model
    def cron_update_admin_hidden_orders(self):
        orders = self.with_context(kds_refresh_admin_visibility=False).search([])
        orders._update_admin_hidden_flags()
        return True

    @api.model
    def cron_clean_old_done_orders(self):
        return True
