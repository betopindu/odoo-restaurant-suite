import base64
import hashlib
import logging

from markupsafe import escape

from odoo import fields, tools
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.einvoice_py.services.py_fiscal_document_delivery_service import (
    PyFiscalDocumentDeliveryService,
)

_logger = logging.getLogger(__name__)


class PyFiscalEmailDeliveryService:
    """Queue authoritative fiscal delivery without changing fiscal state."""

    OPERATOR_GROUP = "einvoice_py.group_py_fiscal_operator"

    def __init__(self, env, delivery_service=None):
        self.env = env
        self.delivery_service = delivery_service or PyFiscalDocumentDeliveryService(env)

    def prepare(self, *, document):
        document.ensure_one()
        prepared = self.delivery_service.prepare_email(document=document)
        self._validated_address(prepared.recipient_email, "receiver snapshot")
        self._sender(document)
        return prepared

    def enqueue(self, *, document, mode="manual"):
        document.ensure_one()
        if mode not in ("manual", "automatic"):
            raise ValidationError("Unsupported fiscal email delivery mode.")
        if mode == "manual" and not self.env.user.has_group(self.OPERATOR_GROUP):
            raise AccessError("Only Paraguay Fiscal Operators may email fiscal documents.")
        prepared = self.prepare(document=document)
        sender = self._sender(document)
        auto_key = False
        if mode == "automatic":
            self.env.cr.execute(
                "SELECT id FROM fiscal_document WHERE id = %s FOR UPDATE",
                [document.id],
            )
            auto_key = "accepted:%s:%s:%s" % (
                document.id,
                document.authority_status or "",
                document.authority_receipt_ref or "",
            )
            existing = self.env["py.fiscal.email.delivery"].sudo().search([
                ("automatic_key", "=", auto_key),
            ], limit=1)
            if existing:
                return existing
        delivery = self.env["py.fiscal.email.delivery"].sudo().create({
            "document_id": document.id,
            "tenant_id": document.tenant_id.id,
            "company_id": document.company_id.id,
            "cdc": document.country_identifier or document.py_cdc,
            "recipient_email": prepared.recipient_email,
            "sender_email": sender,
            "subject": prepared.subject,
            "mode": mode,
            "automatic_key": auto_key,
            "requested_by_id": self.env.user.id,
            "requested_at": fields.Datetime.now(),
            "pdf_source_attachment_id": prepared.attachments[0].fiscal_attachment_id,
            "xml_source_attachment_id": prepared.attachments[1].fiscal_attachment_id,
            "pdf_sha256": prepared.attachments[0].sha256,
            "xml_sha256": prepared.attachments[1].sha256,
        })
        attachment_ids = []
        for item in prepared.attachments:
            attachment = self.env["ir.attachment"].sudo().create({
                "name": item.filename,
                "datas": base64.b64encode(item.content),
                "mimetype": item.mimetype,
                "res_model": delivery._name,
                "res_id": delivery.id,
            })
            attachment_ids.append(attachment.id)
        mail = self.env["mail.mail"].sudo().create({
            "subject": prepared.subject,
            "body_html": "<p>%s</p>" % escape(prepared.body),
            "email_from": sender,
            "email_to": prepared.recipient_email,
            "attachment_ids": [(6, 0, attachment_ids)],
            "auto_delete": False,
        })
        self._validate_outgoing_attachments(mail=mail, prepared=prepared)
        delivery.write({"mail_id": mail.id})
        return delivery

    @staticmethod
    def _validate_outgoing_attachments(*, mail, prepared):
        outgoing = mail._prepare_outgoing_list()
        if len(outgoing) != 1:
            raise ValidationError("Fiscal email MIME preparation is inconsistent.")
        actual = {
            name: hashlib.sha256(content).hexdigest()
            for name, content, _mimetype in outgoing[0]["attachments"]
        }
        expected = {item.filename: item.sha256 for item in prepared.attachments}
        if actual != expected:
            raise ValidationError(
                "Fiscal email MIME does not contain the authoritative KuDE PDF and XML."
            )

    def enqueue_automatic_if_enabled(self, *, document):
        document.ensure_one()
        if not document.company_id.py_auto_email_accepted_fiscal_documents:
            return self.env["py.fiscal.email.delivery"]
        try:
            with self.env.cr.savepoint():
                return self.enqueue(document=document, mode="automatic")
        except Exception as exc:  # Email delivery must never roll back authority acceptance.
            _logger.exception(
                "Automatic Paraguay fiscal email queueing failed for document %s",
                document.id,
            )
            with self.env.cr.savepoint():
                return self._record_automatic_failure(document, exc)

    def _record_automatic_failure(self, document, exc):
        auto_key = "accepted:%s:%s:%s" % (
            document.id,
            document.authority_status or "",
            document.authority_receipt_ref or "",
        )
        existing = self.env["py.fiscal.email.delivery"].sudo().search([
            ("automatic_key", "=", auto_key),
        ], limit=1)
        if existing:
            return existing
        safe_detail = (
            str(exc)
            if isinstance(exc, (ValidationError, AccessError))
            else "Automatic fiscal email preparation failed; inspect the server log."
        )
        return self.env["py.fiscal.email.delivery"].sudo().create({
            "document_id": document.id,
            "tenant_id": document.tenant_id.id,
            "company_id": document.company_id.id,
            "cdc": document.country_identifier or document.py_cdc,
            "recipient_email": (document.customer_email or "").strip(),
            "sender_email": (
                document.company_id.py_fiscal_email_from
                or document.company_id.email
                or ""
            ).strip(),
            "mode": "automatic",
            "automatic_key": auto_key,
            "requested_by_id": self.env.user.id,
            "requested_at": fields.Datetime.now(),
            "preparation_status": "failed",
            "error_category": exc.__class__.__name__,
            "error_detail": safe_detail[:500],
        })

    def _sender(self, document):
        sender = (
            document.company_id.py_fiscal_email_from
            or document.company_id.email
            or ""
        ).strip()
        return self._validated_address(sender, "company sender")

    @staticmethod
    def _validated_address(address, label):
        addresses = tools.email_split(address or "")
        if len(addresses) != 1:
            raise ValidationError(f"A valid {label} email address is required.")
        return addresses[0]
