from odoo import fields, models


class FiscalTransmission(models.Model):
    _name = "fiscal.transmission"
    _description = "Fiscal Transmission"
    _order = "started_at desc, id desc"

    document_id = fields.Many2one("fiscal.document", required=True, ondelete="cascade", index=True)
    tenant_id = fields.Many2one(related="document_id.tenant_id", store=True, readonly=True)
    company_id = fields.Many2one(related="document_id.company_id", store=True, readonly=True)

    attempt_number = fields.Integer(default=1)
    transmission_type = fields.Selection(
        [
            ("submit", "Submit"),
            ("status_query", "Status Query"),
            ("cancel", "Cancel"),
            ("contingency", "Contingency"),
        ],
        default="submit",
        required=True,
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("sent", "Sent"),
            ("accepted", "Accepted"),
            ("rejected", "Rejected"),
            ("failed_retryable", "Failed Retryable"),
            ("failed_final", "Failed Final"),
            ("manual_review", "Manual Review"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    endpoint_url = fields.Char()
    request_hash = fields.Char(index=True)
    response_hash = fields.Char(index=True)
    http_status = fields.Integer()
    authority_status_code = fields.Char(index=True)
    authority_message = fields.Text()
    error_code = fields.Char(index=True)
    error_message = fields.Text()
    error_type = fields.Char(index=True)
    started_at = fields.Datetime(default=fields.Datetime.now)
    finished_at = fields.Datetime()
    duration_ms = fields.Integer()
    next_retry_at = fields.Datetime(index=True)
    metadata_json = fields.Text()
