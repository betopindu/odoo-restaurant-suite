from odoo import fields, models


class FiscalAttachment(models.Model):
    _inherit = "fiscal.attachment"

    attachment_type = fields.Selection(
        selection_add=[
            ("paraguay_payload_json", "Paraguay Payload JSON"),
        ],
        ondelete={"paraguay_payload_json": "cascade"},
    )
