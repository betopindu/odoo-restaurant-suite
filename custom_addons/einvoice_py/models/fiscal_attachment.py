from odoo import fields, models


class FiscalAttachment(models.Model):
    _inherit = "fiscal.attachment"

    attachment_type = fields.Selection(
        selection_add=[
            ("paraguay_payload_json", "Paraguay Payload JSON"),
            ("paraguay_xml_unsigned", "Unsigned XML"),
            ("paraguay_xml_signed", "Signed XML"),
            ("paraguay_qr_payload", "Paraguay QR Payload"),
            ("paraguay_kude_pdf", "Paraguay KuDE PDF"),
        ],
        ondelete={
            "paraguay_payload_json": "cascade",
            "paraguay_xml_unsigned": "cascade",
            "paraguay_xml_signed": "cascade",
            "paraguay_qr_payload": "cascade",
            "paraguay_kude_pdf": "cascade",
        },
    )
