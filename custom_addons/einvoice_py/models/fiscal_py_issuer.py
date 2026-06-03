from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FiscalPyIssuer(models.Model):
    _name = "fiscal.py.issuer"
    _description = "Paraguay Fiscal Issuer"
    _order = "tenant_id, company_id, environment, name"

    name = fields.Char(required=True)
    tenant_id = fields.Many2one("fiscal.tenant", required=True, ondelete="restrict")
    company_id = fields.Many2one("res.company", required=True, ondelete="restrict")
    environment = fields.Selection(
        [
            ("test", "Test"),
            ("production", "Production"),
        ],
        required=True,
        default="test",
    )
    ruc = fields.Char(required=True, string="RUC")
    ruc_dv = fields.Char(required=True, string="RUC DV")
    taxpayer_type = fields.Selection(
        [
            ("1", "Physical Person"),
            ("2", "Legal Entity"),
        ],
        required=True,
    )
    active = fields.Boolean(default=True)
    notes = fields.Text()

    @api.constrains("ruc")
    def _check_ruc(self):
        for record in self:
            if not record.ruc or not record.ruc.isdigit() or len(record.ruc) > 8:
                raise ValidationError("Paraguay issuer RUC must be numeric and at most 8 digits.")

    @api.constrains("ruc_dv")
    def _check_ruc_dv(self):
        for record in self:
            if not record.ruc_dv or not record.ruc_dv.isdigit() or len(record.ruc_dv) != 1:
                raise ValidationError("Paraguay issuer RUC DV must be exactly 1 digit.")

    @api.constrains("active", "tenant_id", "company_id", "environment")
    def _check_unique_active_issuer(self):
        for record in self.filtered("active"):
            duplicate = self.search(
                [
                    ("id", "!=", record.id),
                    ("active", "=", True),
                    ("tenant_id", "=", record.tenant_id.id),
                    ("company_id", "=", record.company_id.id),
                    ("environment", "=", record.environment),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    "Only one active Paraguay issuer is allowed per tenant, "
                    "company, and environment."
                )
