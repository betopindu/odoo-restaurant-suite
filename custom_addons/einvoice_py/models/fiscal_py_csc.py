from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FiscalPyCsc(models.Model):
    _name = "fiscal.py.csc"
    _description = "Paraguay CSC"
    _order = "tenant_id, id_csc"

    name = fields.Char(required=True)
    id_csc = fields.Char(required=True, index=True, string="IdCSC")
    # TODO: replace MVP text storage with encrypted secret storage or KMS integration.
    csc_value = fields.Text(copy=False, groups="base.group_system")
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
    valid_from = fields.Date()
    valid_to = fields.Date()
    active = fields.Boolean(default=True)

    @api.constrains("valid_from", "valid_to")
    def _check_validity_dates(self):
        for record in self:
            if record.valid_from and record.valid_to and record.valid_to < record.valid_from:
                raise ValidationError("CSC valid to date must be on or after valid from date.")

    @api.depends("name", "id_csc", "environment")
    def _compute_display_name(self):
        for record in self:
            label = f"IdCSC {record.id_csc}" if record.id_csc else "CSC"
            if record.name:
                label = f"{label} - {record.name}"
            if record.environment:
                label = f"{label} [{record.environment}]"
            record.display_name = label
