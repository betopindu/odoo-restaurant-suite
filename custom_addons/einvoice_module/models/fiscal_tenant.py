from odoo import fields, models


class FiscalTenant(models.Model):
    _name = "fiscal.tenant"
    _description = "Fiscal Tenant"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(index=True)
    company_id = fields.Many2one("res.company", string="Default Company")
    lock_policy_id = fields.Many2one("fiscal.document.lock.policy")
    active = fields.Boolean(default=True)
