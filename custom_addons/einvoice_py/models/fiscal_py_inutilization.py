from odoo import fields, models


class FiscalPyInutilization(models.Model):
    _name = "fiscal.py.inutilization"
    _description = "Paraguay SIFEN Number Inutilization"
    _order = "id desc"

    tenant_id = fields.Many2one("fiscal.tenant", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one("res.company", required=True, ondelete="restrict", index=True)
    environment = fields.Selection([("test", "Test"), ("production", "Production")], required=True)
    adapter_config_id = fields.Many2one("fiscal.adapter.config", required=True, ondelete="restrict")
    timbrado_id = fields.Many2one("fiscal.py.timbrado", required=True, ondelete="restrict", index=True)
    establishment_id = fields.Many2one("fiscal.py.establishment", required=True, ondelete="restrict", index=True)
    point_of_issue_id = fields.Many2one("fiscal.py.point.of.issue", required=True, ondelete="restrict", index=True)
    document_type = fields.Selection(
        [("invoice", "Invoice"), ("credit_note", "Credit Note"), ("debit_note", "Debit Note")],
        required=True,
    )
    number_from = fields.Integer(required=True, index=True)
    number_to = fields.Integer(required=True, index=True)
    reason = fields.Char(required=True)
    event_id = fields.Char(index=True)
    state = fields.Selection(
        [("pending", "Pending"), ("accepted", "Accepted"), ("rejected", "Rejected"), ("manual_review", "Manual Review")],
        required=True,
        default="pending",
        index=True,
    )
    endpoint_url = fields.Char()
    request_hash = fields.Char(index=True)
    response_hash = fields.Char(index=True)
    http_status = fields.Integer()
    duration_ms = fields.Integer()
    authority_code = fields.Char(index=True)
    authority_message = fields.Text()
    authority_protocol = fields.Char(index=True)
    authority_timestamp = fields.Char()
    started_at = fields.Datetime(default=fields.Datetime.now, required=True)
    finished_at = fields.Datetime()
    metadata_json = fields.Text()

    _sql_constraints = [
        (
            "scope_range_unique",
            "unique(tenant_id, company_id, environment, timbrado_id, establishment_id, point_of_issue_id, document_type, number_from, number_to)",
            "This Paraguay inutilization range already exists in the same fiscal scope.",
        ),
    ]
