from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FiscalPyEstablishment(models.Model):
    _name = "fiscal.py.establishment"
    _description = "Paraguay Fiscal Establishment"
    _order = "tenant_id, code"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    tenant_id = fields.Many2one("fiscal.tenant", required=True, ondelete="restrict")
    company_id = fields.Many2one("res.company", required=True, ondelete="restrict")
    address = fields.Char()
    phone = fields.Char()
    email = fields.Char()
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "code_tenant_company_uniq",
            "unique(code, tenant_id, company_id)",
            "The Paraguay establishment code must be unique per tenant and company.",
        ),
    ]

    @api.constrains("code")
    def _check_code(self):
        for record in self:
            if not record.code or not record.code.isdigit() or len(record.code) != 3:
                raise ValidationError("Paraguay establishment code must be exactly 3 digits.")
