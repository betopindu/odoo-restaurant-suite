import base64
import hashlib
import json

from odoo import api, fields, models


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

    @api.model
    def create_json_payload_attachment(
        self,
        document,
        attachment_type,
        filename,
        payload,
        transmission=None,
    ):
        content = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        content_bytes = content.encode("utf-8")
        ir_attachment = self.env["ir.attachment"].create({
            "name": filename,
            "datas": base64.b64encode(content_bytes),
            "mimetype": "application/json",
            "res_model": "fiscal.document",
            "res_id": document.id,
        })
        return self.create({
            "name": filename,
            "document_id": document.id,
            "transmission_id": transmission.id if transmission else False,
            "attachment_type": attachment_type,
            "mimetype": "application/json",
            "filename": filename,
            "ir_attachment_id": ir_attachment.id,
            "sha256": hashlib.sha256(content_bytes).hexdigest(),
            "is_sensitive": True,
        })
