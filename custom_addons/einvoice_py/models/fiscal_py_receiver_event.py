from odoo import fields, models


class FiscalPyReceiverEvent(models.Model):
    _name = "fiscal.py.receiver.event"
    _description = "Paraguay SIFEN Receiver Event"
    _order = "started_at desc, id desc"

    document_id = fields.Many2one("fiscal.document", required=True, ondelete="restrict", index=True)
    tenant_id = fields.Many2one(related="document_id.tenant_id", store=True, readonly=True)
    company_id = fields.Many2one(related="document_id.company_id", store=True, readonly=True)
    adapter_config_id = fields.Many2one("fiscal.adapter.config", required=True, ondelete="restrict")
    environment = fields.Selection([("test", "Test"), ("production", "Production")], required=True)
    event_type = fields.Selection([
        ("notification", "Receipt Notification"),
        ("conformity_partial", "Partial Conformity"),
        ("conformity_total", "Total Conformity"),
        ("disconformity", "Disconformity"),
        ("unknown", "Unknown Document"),
    ], required=True, index=True)
    event_code = fields.Char(required=True, index=True)
    event_id = fields.Char(index=True)
    target_cdc = fields.Char(required=True, index=True)
    receiver_type = fields.Selection([("1", "Taxpayer"), ("2", "Non-taxpayer")], required=True)
    receiver_name = fields.Char(required=True)
    receiver_ruc = fields.Char(index=True)
    receiver_dv = fields.Char()
    receiver_id_type = fields.Char()
    receiver_id_number = fields.Char(index=True)
    reception_timestamp = fields.Datetime()
    reason = fields.Char()
    state = fields.Selection([
        ("pending", "Pending"), ("accepted", "Accepted"),
        ("rejected", "Rejected"), ("manual_review", "Manual Review"),
    ], default="pending", required=True, index=True)
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

    _sql_constraints = [(
        "event_identity_unique",
        "unique(tenant_id, company_id, environment, target_cdc, event_type, event_id)",
        "This Paraguay receiver event identity already exists.",
    )]
