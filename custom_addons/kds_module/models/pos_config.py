from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    kds_warning_minutes = fields.Integer(
        string="KDS Warning (min)",
        default=5,
    )
    kds_danger_minutes = fields.Integer(
        string="KDS Danger (min)",
        default=10,
    )
    kds_show_done_lane = fields.Boolean(
        string="Mostrar carril Entregado",
        default=False,
    )
    kds_refresh_seconds = fields.Integer(
        string="Auto refresh (segundos)",
        default=10,
    )
    kds_enable_sound = fields.Boolean(
        string="Reproducir sonido al llegar pedido",
        default=True,
    )
    kds_done_visible_minutes = fields.Integer(
        string="Entregados visibles en Display (min)",
        default=180,
    )
    kds_admin_done_visible_hours = fields.Integer(
        string="Entregados visibles en Cocina (horas)",
        default=24,
        help="Cantidad de horas que una orden Entregada seguirá visible en la vista administrativa de Cocina.",
    )

    def action_open_kds_display(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/kitchen/display?config_id={self.id}",
            "target": "new",
        }
