from odoo import fields, models


class FiscalEvent(models.Model):
    _name = "fiscal.event"
    _description = "Fiscal Event"
    _order = "occurred_at desc, id desc"

    document_id = fields.Many2one("fiscal.document", required=True, ondelete="cascade", index=True)
    tenant_id = fields.Many2one(related="document_id.tenant_id", store=True, readonly=True)
    company_id = fields.Many2one(related="document_id.company_id", store=True, readonly=True)

    event_type = fields.Char(required=True, index=True)
    from_state = fields.Char()
    to_state = fields.Char()
    message = fields.Text()
    actor_type = fields.Selection(
        [
            ("system", "System"),
            ("user", "User"),
            ("api", "API"),
            ("cron", "Cron"),
            ("adapter", "Adapter"),
        ],
        default="system",
        required=True,
    )
    user_id = fields.Many2one("res.users")
    occurred_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    payload_hash = fields.Char(index=True)
    metadata_json = fields.Text()
