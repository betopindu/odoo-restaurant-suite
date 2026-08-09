import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from types import MappingProxyType

from lxml import etree

from odoo.exceptions import AccessError, ValidationError

from odoo.addons.einvoice_py.services.py_xml_signature_verification_service import (
    PyXmlSignatureVerificationService,
)


@dataclass(frozen=True, slots=True)
class PyFiscalDeliveryFile:
    kind: str
    filename: str
    mimetype: str
    content: bytes = field(repr=False)
    sha256: str
    fiscal_attachment_id: int


@dataclass(frozen=True, slots=True)
class PyFiscalDocumentDeliveryBundle:
    pdf: PyFiscalDeliveryFile
    xml: PyFiscalDeliveryFile
    document: dict


@dataclass(frozen=True, slots=True)
class PyFiscalDocumentEmailPreparation:
    recipient_email: str
    subject: str
    body: str
    attachments: tuple


class PyFiscalDocumentDeliveryService:
    """Resolve recipient-safe Paraguay artifacts without creating new ones."""

    PDF_TYPE = "paraguay_kude_pdf"
    XML_TYPE = "paraguay_rde_final"
    SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
    DS_NS = "http://www.w3.org/2000/09/xmldsig#"
    DOCUMENT_PREFIXES = {
        "invoice": "FE",
        "credit_note": "NCE",
        "debit_note": "NDE",
    }

    def __init__(self, env, signature_verification_service=None):
        self.env = env
        self.signature_verification_service = (
            signature_verification_service
            if signature_verification_service is not None
            else PyXmlSignatureVerificationService()
        )

    def resolve(self, *, document):
        document.ensure_one()
        self._check_access(document)
        self._validate_eligibility(document)
        stem = self._filename_stem(document)
        pdf_attachment = self._current_attachment(document, self.PDF_TYPE)
        xml_attachment = self._current_attachment(document, self.XML_TYPE)
        pdf = self._file(pdf_attachment, "pdf", f"{stem}.pdf", "application/pdf")
        xml = self._file(xml_attachment, "xml", f"{stem}.xml", "application/xml")
        if not pdf.content.startswith(b"%PDF-"):
            raise ValidationError("Current Paraguay KuDE PDF is invalid for delivery.")
        self._validate_final_rde(xml.content, document)
        return PyFiscalDocumentDeliveryBundle(
            pdf=pdf,
            xml=xml,
            document=MappingProxyType(self._document_summary(document)),
        )

    def prepare_email(self, *, document):
        bundle = self.resolve(document=document)
        recipient = (document.customer_email or document.partner_id.email or "").strip()
        number = bundle.document["document_number"]
        return PyFiscalDocumentEmailPreparation(
            recipient_email=recipient,
            subject=f"Documento electrónico {number}",
            body=(
                f"Adjuntamos el documento electrónico {number} y su KuDE. "
                "Conserve ambos archivos para sus registros."
            ),
            attachments=(bundle.pdf, bundle.xml),
        )

    def _check_access(self, document):
        document.check_access_rights("read")
        document.check_access_rule("read")
        if document.company_id not in self.env.companies:
            raise AccessError("Fiscal document company is not available to the current user.")

    def _validate_eligibility(self, document):
        if (document.country_code or "").upper() != "PY":
            raise ValidationError("Delivery requires a Paraguay fiscal document.")
        if document.state != "accepted":
            raise ValidationError("Only accepted Paraguay fiscal documents are deliverable.")
        if not (document.country_identifier or document.py_cdc):
            raise ValidationError("Accepted Paraguay document CDC is missing.")

    def _current_attachment(self, document, attachment_type):
        attachments = self.env["fiscal.attachment"].sudo().search([
            ("document_id", "=", document.id),
            ("tenant_id", "=", document.tenant_id.id),
            ("company_id", "=", document.company_id.id),
            ("attachment_type", "=", attachment_type),
        ], order="id desc")
        current = attachments.filtered(
            lambda attachment: self._metadata(attachment).get("artifact_status") == "current"
        )
        if len(current) > 1:
            raise ValidationError("Paraguay delivery artifact lifecycle is inconsistent.")
        if current:
            return current
        legacy = attachments.filtered(
            lambda attachment: self._metadata(attachment).get("artifact_status")
            not in ("superseded",)
        )[:1]
        if legacy:
            return legacy
        label = "KuDE PDF" if attachment_type == self.PDF_TYPE else "final signed XML"
        raise ValidationError(f"Current Paraguay {label} is missing for delivery.")

    def _file(self, attachment, kind, filename, expected_mimetype):
        if not attachment.ir_attachment_id:
            raise ValidationError("Current Paraguay delivery artifact content is missing.")
        try:
            content = base64.b64decode(
                attachment.ir_attachment_id.datas or b"",
                validate=True,
            )
        except (TypeError, ValueError):
            raise ValidationError("Current Paraguay delivery artifact is invalid.") from None
        digest = hashlib.sha256(content).hexdigest()
        if not attachment.sha256 or digest != attachment.sha256:
            raise ValidationError("Current Paraguay delivery artifact integrity check failed.")
        if attachment.mimetype and attachment.mimetype != expected_mimetype:
            raise ValidationError("Current Paraguay delivery artifact media type is invalid.")
        return PyFiscalDeliveryFile(
            kind=kind,
            filename=filename,
            mimetype=expected_mimetype,
            content=content,
            sha256=digest,
            fiscal_attachment_id=attachment.id,
        )

    def _validate_final_rde(self, xml_bytes, document):
        try:
            parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
            root = etree.fromstring(xml_bytes, parser)
        except etree.XMLSyntaxError:
            raise ValidationError("Current Paraguay final signed XML is invalid for delivery.") from None
        if root.tag != f"{{{self.SIFEN_NS}}}rDE":
            raise ValidationError("Current Paraguay XML is not a final rDE.")
        de_nodes = root.findall(f"{{{self.SIFEN_NS}}}DE")
        signatures = root.findall(f"{{{self.DS_NS}}}Signature")
        qr_groups = root.findall(f"{{{self.SIFEN_NS}}}gCamFuFD")
        if len(de_nodes) != 1 or len(signatures) != 1 or len(qr_groups) != 1:
            raise ValidationError("Current Paraguay XML is not complete for recipient delivery.")
        qr_value = qr_groups[0].find(f"{{{self.SIFEN_NS}}}dCarQR")
        cdc = (document.country_identifier or document.py_cdc or "").strip()
        if de_nodes[0].get("Id") != cdc or qr_value is None or not (qr_value.text or "").strip():
            raise ValidationError("Current Paraguay final rDE identity is invalid for delivery.")
        verification = self.signature_verification_service.verify(
            signed_xml_bytes=xml_bytes,
            expected_cdc=cdc,
        )
        if not verification.get("valid"):
            raise ValidationError("Current Paraguay final rDE signature is invalid for delivery.")

    def _filename_stem(self, document):
        prefix = self.DOCUMENT_PREFIXES.get(document.document_type, "DE")
        number = (document.py_full_number or document.fiscal_number or "").strip()
        if not number or not re.fullmatch(r"[0-9-]+", number):
            raise ValidationError("Paraguay recipient filename requires a safe document number.")
        return f"{prefix}-{number}"

    def _document_summary(self, document):
        return {
            "cdc": document.country_identifier or document.py_cdc,
            "document_number": document.py_full_number or document.fiscal_number,
            "document_type": document.document_type,
            "issuer": document.py_issuer_id.name or document.company_id.name,
            "company": document.company_id.name,
            "receiver": document.customer_name or document.partner_id.name or "",
            "receiver_email": document.customer_email or document.partner_id.email or "",
            "environment": document.environment,
            "authority_state": document.authority_status or document.state,
        }

    def _metadata(self, attachment):
        try:
            value = json.loads(attachment.metadata_json or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}
