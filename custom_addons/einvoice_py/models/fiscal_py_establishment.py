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
    issuer_id = fields.Many2one("fiscal.py.issuer", ondelete="restrict")
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

    @api.constrains("active", "issuer_id")
    def _check_active_has_issuer(self):
        for record in self:
            if record.active and not record.issuer_id:
                raise ValidationError("Active Paraguay establishments require an issuer.")

    @api.constrains("tenant_id", "company_id", "issuer_id")
    def _check_issuer_scope(self):
        for record in self.filtered("issuer_id"):
            if (
                record.issuer_id.tenant_id != record.tenant_id
                or record.issuer_id.company_id != record.company_id
            ):
                raise ValidationError(
                    "Paraguay establishment issuer must use the same tenant and company."
                )

    @api.depends("name", "code", "issuer_id")
    def _compute_display_name(self):
        for record in self:
            label = record.name or "Establishment"
            if record.code:
                label = f"{record.code} - {label}"
            if record.issuer_id and record.issuer_id.ruc:
                label = f"{label} ({record.issuer_id.ruc}-{record.issuer_id.ruc_dv})"
            record.display_name = label
