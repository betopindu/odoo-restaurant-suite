import base64
import hashlib
import json

from odoo.exceptions import ValidationError


class PySourceArtifactService:
    """Persist and resolve the current Paraguay payload and unsigned XML."""

    PAYLOAD_TYPE = "paraguay_payload_json"
    UNSIGNED_XML_TYPE = "paraguay_xml_unsigned"

    def __init__(self, env):
        self.env = env

    def persist_payload(self, *, document, payload, filename=None):
        document.ensure_one()
        self._lock(document)
        self._validate_payload(document, payload)
        content = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return self._persist(
            document=document,
            attachment_type=self.PAYLOAD_TYPE,
            content=content,
            filename=filename or f"{document.uuid}-paraguay-payload.json",
            mimetype="application/json",
            metadata={"cdc": self._document_cdc(document)},
        )

    def read_current_payload(self, *, document):
        attachment, content, _metadata = self._read_current(
            document=document,
            attachment_type=self.PAYLOAD_TYPE,
        )
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, TypeError):
            raise ValidationError("Current Paraguay payload artifact is invalid.") from None
        self._validate_payload(document, payload)
        return attachment, payload

    def persist_unsigned_xml(
        self,
        *,
        document,
        unsigned_xml_bytes,
        payload_attachment,
        filename=None,
    ):
        document.ensure_one()
        payload_attachment.ensure_one()
        self._lock(document)
        self._validate_attachment_scope(
            document, payload_attachment, self.PAYLOAD_TYPE
        )
        current_payload, _payload = self.read_current_payload(document=document)
        if current_payload != payload_attachment:
            raise ValidationError(
                "Paraguay unsigned XML requires the current payload artifact."
            )
        if isinstance(unsigned_xml_bytes, str):
            unsigned_xml_bytes = unsigned_xml_bytes.encode("utf-8")
        if not isinstance(unsigned_xml_bytes, bytes) or not unsigned_xml_bytes:
            raise ValidationError("Paraguay unsigned XML artifact is invalid.")
        return self._persist(
            document=document,
            attachment_type=self.UNSIGNED_XML_TYPE,
            content=unsigned_xml_bytes,
            filename=filename or f"{document.uuid}-paraguay-unsigned.xml",
            mimetype="application/xml",
            metadata={
                "cdc": self._document_cdc(document),
                "payload_attachment_id": payload_attachment.id,
                "payload_sha256": payload_attachment.sha256,
            },
        )

    def read_current_unsigned_xml(self, *, document, payload_attachment=None):
        attachment, content, metadata = self._read_current(
            document=document,
            attachment_type=self.UNSIGNED_XML_TYPE,
        )
        if payload_attachment and (
            metadata.get("payload_attachment_id") != payload_attachment.id
            or metadata.get("payload_sha256") != payload_attachment.sha256
        ):
            raise ValidationError(
                "Current Paraguay unsigned XML provenance is inconsistent."
            )
        return attachment, content

    def _persist(
        self,
        *,
        document,
        attachment_type,
        content,
        filename,
        mimetype,
        metadata,
    ):
        digest = hashlib.sha256(content).hexdigest()
        attachments = self._attachments(document, attachment_type)
        identical = attachments.filtered(lambda item: item.sha256 == digest)[:1]
        if identical:
            self._validate_stored_content(identical, content)
            values = dict(metadata, artifact_status="current")
            self._write_metadata(identical, values)
            self._mark_superseded(attachments - identical, identical)
            return identical

        current = self._explicit_current(attachments)
        if len(current) > 1:
            raise ValidationError("Paraguay source artifact lifecycle is ambiguous.")
        previous = current[:1] or attachments[:1]
        values = dict(metadata, artifact_status="current")
        if previous:
            values["supersedes_attachment_id"] = previous.id
        ir_attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(content),
            "mimetype": mimetype,
            "res_model": "fiscal.document",
            "res_id": document.id,
        })
        attachment = self.env["fiscal.attachment"].sudo().create({
            "name": filename,
            "document_id": document.id,
            "attachment_type": attachment_type,
            "mimetype": mimetype,
            "filename": filename,
            "ir_attachment_id": ir_attachment.id,
            "sha256": digest,
            "is_sensitive": True,
            "metadata_json": self._metadata_json(values),
        })
        self._mark_superseded(attachments, attachment)
        return attachment

    def _read_current(self, *, document, attachment_type):
        document.ensure_one()
        attachments = self._attachments(document, attachment_type)
        current = self._explicit_current(attachments)
        if len(current) > 1:
            raise ValidationError("Paraguay source artifact lifecycle is ambiguous.")
        if current:
            attachment = current
        else:
            legacy = attachments.filtered(
                lambda item: not self._metadata(item).get("artifact_status")
            )
            if len(legacy) != 1 or len(attachments) != 1:
                raise ValidationError(
                    "Current Paraguay source artifact cannot be resolved safely."
                )
            attachment = legacy
        self._validate_attachment_scope(document, attachment, attachment_type)
        content = self._content(attachment)
        metadata = self._metadata(attachment)
        metadata_cdc = str(metadata.get("cdc") or "")
        if metadata_cdc and metadata_cdc != self._document_cdc(document):
            raise ValidationError("Current Paraguay source artifact CDC is inconsistent.")
        return attachment, content, metadata

    def _validate_payload(self, document, payload):
        if not isinstance(payload, dict):
            raise ValidationError("Paraguay payload artifact must contain a dictionary.")
        cdc = str(payload.get("cdc") or "").strip()
        nested_cdc = str((payload.get("document") or {}).get("py_cdc") or "").strip()
        expected = self._document_cdc(document)
        if not expected or cdc != expected or nested_cdc != expected:
            raise ValidationError("Paraguay payload CDC does not match the fiscal document.")

    def _validate_attachment_scope(self, document, attachment, attachment_type):
        if (
            not attachment
            or attachment.document_id != document
            or attachment.tenant_id != document.tenant_id
            or attachment.company_id != document.company_id
            or attachment.attachment_type != attachment_type
            or not attachment.ir_attachment_id
            or attachment.ir_attachment_id.res_model != "fiscal.document"
            or attachment.ir_attachment_id.res_id != document.id
        ):
            raise ValidationError("Paraguay source artifact scope is invalid.")

    def _content(self, attachment):
        try:
            content = base64.b64decode(
                attachment.ir_attachment_id.datas or b"", validate=True
            )
        except (TypeError, ValueError):
            raise ValidationError("Current Paraguay source artifact is invalid.") from None
        if not attachment.sha256 or hashlib.sha256(content).hexdigest() != attachment.sha256:
            raise ValidationError("Current Paraguay source artifact integrity check failed.")
        return content

    def _validate_stored_content(self, attachment, expected):
        if self._content(attachment) != expected:
            raise ValidationError("Paraguay source artifact hash collision was detected.")

    def _attachments(self, document, attachment_type):
        return self.env["fiscal.attachment"].sudo().search([
            ("document_id", "=", document.id),
            ("attachment_type", "=", attachment_type),
        ], order="id desc")

    def _explicit_current(self, attachments):
        return attachments.filtered(
            lambda item: self._metadata(item).get("artifact_status") == "current"
        )

    def _mark_superseded(self, attachments, current):
        for attachment in attachments:
            metadata = self._metadata(attachment)
            metadata["artifact_status"] = "superseded"
            metadata["superseded_by_attachment_id"] = current.id
            self._write_metadata(attachment, metadata)

    def _write_metadata(self, attachment, metadata):
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
            "payload_attachment_id",
            "payload_sha256",
            "superseded_by_attachment_id",
            "supersedes_attachment_id",
        )
        return json.dumps(
            {key: metadata[key] for key in allowed if metadata.get(key) not in (None, "")},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _document_cdc(self, document):
        py_cdc = (document.py_cdc or "").strip()
        country_identifier = (document.country_identifier or "").strip()
        if not py_cdc or py_cdc != country_identifier:
            raise ValidationError("Paraguay fiscal document CDC is inconsistent.")
        return py_cdc

    def _lock(self, document):
        self.env.cr.execute(
            "SELECT id FROM fiscal_document WHERE id = %s FOR UPDATE", [document.id]
        )
        if not self.env.cr.fetchone():
            raise ValidationError("Paraguay source artifact document no longer exists.")
