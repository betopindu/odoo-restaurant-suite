from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FiscalPyPointOfIssue(models.Model):
    _name = "fiscal.py.point.of.issue"
    _description = "Paraguay Fiscal Point of Issue"
    _order = "establishment_id, code"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    establishment_id = fields.Many2one(
        "fiscal.py.establishment",
        required=True,
        ondelete="restrict",
    )
    tenant_id = fields.Many2one(
        "fiscal.tenant",
        related="establishment_id.tenant_id",
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="establishment_id.company_id",
        store=True,
        readonly=True,
    )
    active = fields.Boolean(default=True)
    sequence_id = fields.Many2one("ir.sequence")

    _sql_constraints = [
        (
            "code_establishment_uniq",
            "unique(code, establishment_id)",
            "The Paraguay point of issue code must be unique per establishment.",
        ),
    ]

    @api.constrains("code")
    def _check_code(self):
        for record in self:
            if not record.code or not record.code.isdigit() or len(record.code) != 3:
                raise ValidationError("Paraguay point of issue code must be exactly 3 digits.")
