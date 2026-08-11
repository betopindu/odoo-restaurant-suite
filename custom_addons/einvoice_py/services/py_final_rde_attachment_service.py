import base64
import hashlib
import json

from odoo.exceptions import ValidationError


class PyFinalRdeAttachmentService:
    """Persist the recipient-ready final Paraguay rDE with audit history."""

    ATTACHMENT_TYPE = "paraguay_rde_final"

    def __init__(self, env):
        self.env = env

    def persist(
        self,
        *,
        document,
        final_xml_bytes,
        cdc,
        filename=None,
        signed_attachment_id=None,
        signed_xml_sha256=None,
        qr_attachment_id=None,
        qr_sha256=None,
    ):
        document.ensure_one()
        self._lock_document(document)
        if isinstance(final_xml_bytes, str):
            final_xml_bytes = final_xml_bytes.encode("utf-8")
        digest = hashlib.sha256(final_xml_bytes).hexdigest()
        attachments = self._attachments(document)
        identical = attachments.filtered(lambda attachment: attachment.sha256 == digest)[:1]
        if identical:
            self._mark_current(identical, attachments - identical)
            return identical
        previous = attachments[:1]
        metadata = {
            "artifact_status": "current",
            "cdc": cdc,
            "signed_attachment_id": signed_attachment_id,
            "signed_xml_sha256": signed_xml_sha256,
            "qr_attachment_id": qr_attachment_id,
            "qr_sha256": qr_sha256,
        }
        if previous:
            metadata["supersedes_attachment_id"] = previous.id
        filename = filename or f"{document.uuid}-paraguay-rde.xml"
        ir_attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(final_xml_bytes),
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
            "sha256": digest,
            "is_sensitive": True,
            "metadata_json": self._metadata_json(metadata),
        })
        self._mark_superseded(attachments, attachment)
        return attachment

    def current(self, *, document):
        document.ensure_one()
        attachments = self._attachments(document)
        current = attachments.filtered(
            lambda attachment: self._metadata(attachment).get("artifact_status") == "current"
        )[:1]
        return current or attachments.filtered(
            lambda attachment: self._metadata(attachment).get("artifact_status") != "superseded"
        )[:1]

    def _attachments(self, document):
        return self.env["fiscal.attachment"].sudo().search([
            ("document_id", "=", document.id),
            ("attachment_type", "=", self.ATTACHMENT_TYPE),
        ], order="id desc")

    def _lock_document(self, document):
        self.env.cr.execute(
            "SELECT id FROM fiscal_document WHERE id = %s FOR UPDATE",
            [document.id],
        )
        if not self.env.cr.fetchone():
            raise ValidationError("Final Paraguay rDE document no longer exists.")

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
            return {}
        return value if isinstance(value, dict) else {}

    def _metadata_json(self, metadata):
        allowed = (
            "artifact_status",
            "cdc",
            "signed_attachment_id",
            "signed_xml_sha256",
            "qr_attachment_id",
            "qr_sha256",
            "superseded_by_attachment_id",
            "supersedes_attachment_id",
        )
        return json.dumps(
            {key: metadata[key] for key in allowed if metadata.get(key) not in (None, "")},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
