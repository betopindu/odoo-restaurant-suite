from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FiscalPyEconomicActivity(models.Model):
    _name = "fiscal.py.economic.activity"
    _description = "Paraguay Economic Activity"
    _order = "issuer_id, sequence, code"

    issuer_id = fields.Many2one(
        "fiscal.py.issuer",
        required=True,
        ondelete="cascade",
    )
    tenant_id = fields.Many2one(
        "fiscal.tenant",
        related="issuer_id.tenant_id",
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="issuer_id.company_id",
        store=True,
        readonly=True,
    )
    code = fields.Char(required=True, index=True)
    description = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "issuer_code_uniq",
            "unique(issuer_id, code)",
            "The Paraguay economic activity code must be unique per issuer.",
        ),
    ]

    @api.constrains("code")
    def _check_code(self):
        for record in self:
            if not record.code:
                raise ValidationError("Paraguay economic activity code is required.")
            if not record.code.isalnum() or len(record.code) > 8:
                raise ValidationError(
                    "Paraguay economic activity code must be alphanumeric and at most 8 characters."
                )

    @api.constrains("description")
    def _check_description(self):
        for record in self:
            if not record.description:
                raise ValidationError("Paraguay economic activity description is required.")

    @api.constrains("issuer_id", "code")
    def _check_unique_code_per_issuer(self):
        for record in self:
            if not record.issuer_id or not record.code:
                continue
            duplicate = self.search(
                [
                    ("id", "!=", record.id),
                    ("issuer_id", "=", record.issuer_id.id),
                    ("code", "=", record.code),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    "The Paraguay economic activity code must be unique per issuer."
                )

    @api.depends("code", "description")
    def _compute_display_name(self):
        for record in self:
            if record.code and record.description:
                record.display_name = f"{record.code} - {record.description}"
            else:
                record.display_name = record.code or record.description or "Economic Activity"
