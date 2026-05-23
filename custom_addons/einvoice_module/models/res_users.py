from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    allowed_fiscal_tenant_ids = fields.Many2many(
        "fiscal.tenant",
        "res_users_fiscal_tenant_rel",
        "user_id",
        "tenant_id",
        string="Allowed Fiscal Tenants",
    )
