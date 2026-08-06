import base64
import hashlib
import json
import re
from urllib.parse import parse_qs, urlsplit

from odoo.exceptions import ValidationError


class PyQrPayloadAttachmentService:
    """Persist the exact SIFEN QR URL without recalculating its contents."""

    ATTACHMENT_TYPE = "paraguay_qr_payload"
    HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

    def __init__(self, env):
        self.env = env

    def persist(self, *, document, qr_payload, qr_hash, filename=None):
        document.ensure_one()
        self._lock_document(document)
        content = self._validated_content(document, qr_payload, qr_hash)
        content_hash = hashlib.sha256(content).hexdigest()
        attachments = self._attachments(document)
        identical = attachments.filtered(
            lambda item: item.sha256 == content_hash
        )[:1]
        if identical:
            self._mark_current(identical, attachments - identical)
            return identical

        previous = attachments[:1]
        metadata = {
            "artifact_status": "current",
            "cdc": document.py_cdc or document.country_identifier,
            "qr_hash": qr_hash,
        }
        if previous:
            metadata["supersedes_attachment_id"] = previous.id
        filename = filename or f"{document.uuid}-paraguay-qr.txt"
        ir_attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(content),
            "mimetype": "text/uri-list",
            "res_model": "fiscal.document",
            "res_id": document.id,
        })
        attachment = self.env["fiscal.attachment"].sudo().create({
            "name": filename,
            "document_id": document.id,
            "attachment_type": self.ATTACHMENT_TYPE,
            "mimetype": "text/uri-list",
            "filename": filename,
            "ir_attachment_id": ir_attachment.id,
            "sha256": content_hash,
            "is_sensitive": True,
            "metadata_json": self._metadata_json(metadata),
        })
        self._mark_superseded(attachments, attachment)
        return attachment

    def current(self, *, document):
        document.ensure_one()
        attachments = self._attachments(document)
        current = attachments.filtered(
            lambda item: self._metadata(item).get("artifact_status") == "current"
        )[:1]
        return current or attachments[:1]

    def read_current(self, *, document):
        attachment = self.current(document=document)
        if not attachment or not attachment.ir_attachment_id:
            raise ValidationError("Persisted Paraguay QR payload is missing.")
        try:
            content = base64.b64decode(
                attachment.ir_attachment_id.datas or b"",
                validate=True,
            )
            qr_payload = content.decode("utf-8")
        except (TypeError, ValueError, UnicodeDecodeError):
            raise ValidationError(
                "Persisted Paraguay QR payload is invalid."
            ) from None
        metadata = self._metadata(attachment)
        self._validated_content(
            document,
            qr_payload,
            metadata.get("qr_hash"),
        )
        if hashlib.sha256(content).hexdigest() != attachment.sha256:
            raise ValidationError(
                "Persisted Paraguay QR payload integrity check failed."
            )
        return attachment, qr_payload

    def _validated_content(self, document, qr_payload, qr_hash):
        if not isinstance(qr_payload, str) or not qr_payload.strip():
            raise ValidationError("Paraguay QR payload is required.")
        qr_payload = qr_payload.strip()
        if not isinstance(qr_hash, str) or not self.HASH_PATTERN.fullmatch(qr_hash):
            raise ValidationError("Paraguay QR hash is invalid.")
        try:
            parsed = urlsplit(qr_payload)
            query = parse_qs(parsed.query, keep_blank_values=True)
        except ValueError:
            raise ValidationError("Paraguay QR payload is invalid.") from None
        cdc = (document.py_cdc or document.country_identifier or "").strip()
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.fragment
            or query.get("Id") != [cdc]
            or query.get("cHashQR") != [qr_hash]
        ):
            raise ValidationError("Paraguay QR payload does not match the document.")
        return qr_payload.encode("utf-8")

    def _attachments(self, document):
        return self.env["fiscal.attachment"].sudo().search(
            [
                ("document_id", "=", document.id),
                ("attachment_type", "=", self.ATTACHMENT_TYPE),
            ],
            order="id desc",
        )

    def _lock_document(self, document):
        self.env.cr.execute(
            "SELECT id FROM fiscal_document WHERE id = %s FOR UPDATE",
            [document.id],
        )
        if not self.env.cr.fetchone():
            raise ValidationError("Paraguay QR document no longer exists.")

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
        allowed = (
            "artifact_status",
            "cdc",
            "qr_hash",
            "superseded_by_attachment_id",
            "supersedes_attachment_id",
        )
        return json.dumps(
            {key: metadata[key] for key in allowed if metadata.get(key) not in (None, "")},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
