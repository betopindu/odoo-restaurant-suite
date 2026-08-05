import base64
import hashlib
import json

from odoo.exceptions import ValidationError


class PySignedXmlAttachmentService:
    """Persist signed Paraguay XML as a separate sensitive fiscal attachment."""

    ATTACHMENT_TYPE = "paraguay_xml_signed"

    def __init__(self, env):
        self.env = env

    def persist(self, *, document, signed_xml_bytes, filename, metadata=None):
        document.ensure_one()
        self._lock_document(document)
        if isinstance(signed_xml_bytes, str):
            signed_xml_bytes = signed_xml_bytes.encode("utf-8")
        content_hash = hashlib.sha256(signed_xml_bytes).hexdigest()
        attachments = self.env["fiscal.attachment"].sudo().search(
            [
                ("document_id", "=", document.id),
                ("attachment_type", "=", self.ATTACHMENT_TYPE),
            ], order="id desc",
        )
        identical = attachments.filtered(lambda item: item.sha256 == content_hash)[:1]
        if identical:
            self._mark_current(identical, attachments - identical)
            return identical

        previous = attachments[:1]
        current_metadata = dict(metadata or {})
        current_metadata["artifact_status"] = "current"
        if previous:
            current_metadata["supersedes_attachment_id"] = previous.id
        metadata_json = self._metadata_json(current_metadata)
        ir_attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(signed_xml_bytes),
            "mimetype": "application/xml",
            "res_model": "fiscal.document",
            "res_id": document.id,
        })
        attachment = self.env["fiscal.attachment"].sudo().create({
            "name": filename,
            "document_id": document.id,
            "attachment_type": self.ATTACHMENT_TYPE,
            "mimetype": "application/xml",
            "filename": filename,
            "ir_attachment_id": ir_attachment.id,
            "sha256": content_hash,
            "is_sensitive": True,
            "metadata_json": metadata_json,
        })
        self._mark_superseded(attachments, attachment)
        return attachment

    def current(self, *, document):
        document.ensure_one()
        attachments = self.env["fiscal.attachment"].sudo().search(
            [
                ("document_id", "=", document.id),
                ("attachment_type", "=", self.ATTACHMENT_TYPE),
            ],
            order="id desc",
        )
        current = attachments.filtered(
            lambda item: self._metadata(item).get("artifact_status") == "current"
        )[:1]
        return current or attachments[:1]

    def _lock_document(self, document):
        self.env.cr.execute(
            "SELECT id FROM fiscal_document WHERE id = %s FOR UPDATE",
            [document.id],
        )
        locked = self.env.cr.fetchone()
        if not locked:
            raise ValidationError("Paraguay signed XML document no longer exists.")

    def _mark_current(self, current, superseded):
        metadata = self._metadata(current)
        metadata["artifact_status"] = "current"
        metadata.pop("superseded_by_attachment_id", None)
        current.write({"metadata_json": self._metadata_json(metadata)})
        self._mark_superseded(superseded, current)

    def _mark_superseded(self, attachments, current):
        for attachment in attachments:
            metadata = self._metadata(attachment)
            metadata["artifact_status"] = "superseded"
            metadata["superseded_by_attachment_id"] = current.id
            attachment.write({"metadata_json": self._metadata_json(metadata)})

    def _metadata(self, attachment):
        try:
            value = json.loads(attachment.metadata_json or "{}")
        except (TypeError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _metadata_json(self, metadata):
        allowed_keys = (
            "cdc",
            "digest_value",
            "certificate_fingerprint_sha256",
            "signing_time",
            "artifact_status",
            "superseded_by_attachment_id",
            "supersedes_attachment_id",
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
