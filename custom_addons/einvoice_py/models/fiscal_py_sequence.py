from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FiscalPySequence(models.Model):
    _name = "fiscal.py.sequence"
    _description = "Paraguay Fiscal Sequence"
    _order = "tenant_id, establishment_id, point_of_issue_id, document_type"

    name = fields.Char(required=True)
    tenant_id = fields.Many2one("fiscal.tenant", required=True, ondelete="restrict")
    company_id = fields.Many2one("res.company", required=True, ondelete="restrict")
    timbrado_id = fields.Many2one("fiscal.py.timbrado", required=True, ondelete="restrict")
    establishment_id = fields.Many2one(
        "fiscal.py.establishment",
        required=True,
        ondelete="restrict",
    )
    point_of_issue_id = fields.Many2one(
        "fiscal.py.point.of.issue",
        required=True,
        ondelete="restrict",
    )
    document_type = fields.Selection(
        [
            ("invoice", "Invoice"),
            ("credit_note", "Credit Note"),
            ("debit_note", "Debit Note"),
            ("receipt", "Receipt"),
        ],
        required=True,
        default="invoice",
    )
    next_number = fields.Integer(required=True, default=1)
    padding = fields.Integer(required=True, default=7)
    active = fields.Boolean(default=True)

    @api.constrains("next_number")
    def _check_next_number(self):
        for record in self:
            if record.next_number <= 0:
                raise ValidationError("Paraguay sequence next number must be greater than zero.")

    @api.constrains("padding")
    def _check_padding(self):
        for record in self:
            if record.padding < 1:
                raise ValidationError("Paraguay sequence padding must be at least 1.")

    @api.constrains(
        "active",
        "tenant_id",
        "company_id",
        "timbrado_id",
        "establishment_id",
        "point_of_issue_id",
        "document_type",
    )
    def _check_unique_active_sequence(self):
        for record in self.filtered("active"):
            duplicate = self.search(
                [
                    ("id", "!=", record.id),
                    ("active", "=", True),
                    ("tenant_id", "=", record.tenant_id.id),
                    ("company_id", "=", record.company_id.id),
                    ("timbrado_id", "=", record.timbrado_id.id),
                    ("establishment_id", "=", record.establishment_id.id),
                    ("point_of_issue_id", "=", record.point_of_issue_id.id),
                    ("document_type", "=", record.document_type),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    "Only one active Paraguay sequence is allowed for the same "
                    "tenant, company, timbrado, establishment, point of issue, "
                    "and document type."
                )

    @api.depends(
        "name",
        "document_type",
        "establishment_id.code",
        "point_of_issue_id.code",
        "timbrado_id.number",
        "next_number",
    )
    def _compute_display_name(self):
        document_types = dict(self._fields["document_type"].selection)
        for record in self:
            parts = []
            if record.establishment_id.code and record.point_of_issue_id.code:
                parts.append(f"{record.establishment_id.code}-{record.point_of_issue_id.code}")
            if record.document_type:
                parts.append(document_types.get(record.document_type, record.document_type))
            if record.timbrado_id.number:
                parts.append(f"Timbrado {record.timbrado_id.number}")
            if record.next_number:
                parts.append(f"Next {record.next_number}")
            record.display_name = " | ".join(parts) or record.name or "Paraguay Sequence"
