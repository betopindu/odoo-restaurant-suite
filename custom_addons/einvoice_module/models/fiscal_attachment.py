from odoo import fields, models


class FiscalAttachment(models.Model):
    _name = "fiscal.attachment"
    _description = "Fiscal Attachment"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True)
    document_id = fields.Many2one("fiscal.document", required=True, ondelete="cascade", index=True)
    transmission_id = fields.Many2one("fiscal.transmission", ondelete="set null", index=True)
    tenant_id = fields.Many2one(related="document_id.tenant_id", store=True, readonly=True)
    company_id = fields.Many2one(related="document_id.company_id", store=True, readonly=True)

    attachment_type = fields.Selection(
        [
            ("canonical_json", "Canonical JSON"),
            ("unsigned_payload", "Unsigned Payload"),
            ("signed_payload", "Signed Payload"),
            ("authority_response", "Authority Response"),
            ("pdf", "PDF"),
            ("qr", "QR"),
            ("hash_manifest", "Hash Manifest"),
        ],
        required=True,
        index=True,
    )
    mimetype = fields.Char()
    filename = fields.Char()
    ir_attachment_id = fields.Many2one("ir.attachment", ondelete="restrict")
    sha256 = fields.Char(index=True)
    is_sensitive = fields.Boolean(default=True)
    metadata_json = fields.Text()
