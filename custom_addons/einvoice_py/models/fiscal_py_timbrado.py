from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FiscalPyTimbrado(models.Model):
    _name = "fiscal.py.timbrado"
    _description = "Paraguay Timbrado"
    _order = "number desc"

    number = fields.Char(required=True, index=True)
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
    document_type = fields.Selection(
        [
            ("invoice", "Invoice"),
            ("credit_note", "Credit Note"),
            ("debit_note", "Debit Note"),
        ],
        required=True,
        default="invoice",
    )
    valid_from = fields.Date()
    valid_to = fields.Date()
    active = fields.Boolean(default=True)
    allowed_point_of_issue_ids = fields.Many2many(
        "fiscal.py.point.of.issue",
        "fiscal_py_timbrado_point_rel",
        "timbrado_id",
        "point_of_issue_id",
        string="Allowed Points of Issue",
    )

    @api.constrains("valid_from", "valid_to")
    def _check_validity_dates(self):
        for record in self:
            if record.valid_from and record.valid_to and record.valid_to < record.valid_from:
                raise ValidationError("Timbrado valid to date must be on or after valid from date.")
