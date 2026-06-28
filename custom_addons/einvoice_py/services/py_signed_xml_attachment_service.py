import base64
import hashlib
import json


class PySignedXmlAttachmentService:
    """Persist signed Paraguay XML as a separate sensitive fiscal attachment."""

    ATTACHMENT_TYPE = "paraguay_xml_signed"

    def __init__(self, env):
        self.env = env

    def persist(self, *, document, signed_xml_bytes, filename, metadata=None):
        document.ensure_one()
        existing = self.env["fiscal.attachment"].sudo().search(
            [
                ("document_id", "=", document.id),
                ("attachment_type", "=", self.ATTACHMENT_TYPE),
            ],
            limit=1,
        )
        if existing:
            return existing

        if isinstance(signed_xml_bytes, str):
            signed_xml_bytes = signed_xml_bytes.encode("utf-8")
        metadata_json = self._metadata_json(metadata or {})
        ir_attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(signed_xml_bytes),
            "mimetype": "application/xml",
            "res_model": "fiscal.document",
            "res_id": document.id,
        })
        return self.env["fiscal.attachment"].sudo().create({
            "name": filename,
            "document_id": document.id,
            "attachment_type": self.ATTACHMENT_TYPE,
            "mimetype": "application/xml",
            "filename": filename,
            "ir_attachment_id": ir_attachment.id,
            "sha256": hashlib.sha256(signed_xml_bytes).hexdigest(),
            "is_sensitive": True,
            "metadata_json": metadata_json,
        })

    def _metadata_json(self, metadata):
        allowed_keys = (
            "cdc",
            "digest_value",
            "certificate_fingerprint_sha256",
            "signing_time",
        )
        values = {
            key: metadata[key]
            for key in allowed_keys
            if metadata.get(key) not in (None, "")
        }
        return json.dumps(
            values,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
