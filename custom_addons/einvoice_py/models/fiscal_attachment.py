from odoo import fields, models


class FiscalAttachment(models.Model):
    _inherit = "fiscal.attachment"

    attachment_type = fields.Selection(
        selection_add=[
            ("paraguay_payload_json", "Paraguay Payload JSON"),
            ("paraguay_xml_unsigned", "Unsigned XML"),
        ],
        ondelete={
            "paraguay_payload_json": "cascade",
            "paraguay_xml_unsigned": "cascade",
        },
    )
