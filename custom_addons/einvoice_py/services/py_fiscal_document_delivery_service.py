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
from odoo.addons.einvoice_py.services.py_sifen_recep_de_response_parser import (
    PySifenRecepDeResponseParser,
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
    CONSULTA_APPROVED_CODE = "0422"
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
        pdf = self.resolve_file(document=document, file_kind="pdf")
        xml = self.resolve_file(document=document, file_kind="xml")
        return PyFiscalDocumentDeliveryBundle(
            pdf=pdf,
            xml=xml,
            document=MappingProxyType(self._document_summary(document)),
        )

    def resolve_file(self, *, document, file_kind):
        """Resolve one authoritative file without coupling it to its sibling."""
        document.ensure_one()
        self._check_access(document)
        self._validate_eligibility(document)
        stem = self._filename_stem(document)
        if file_kind == "pdf":
            attachment = self._current_attachment(document, self.PDF_TYPE)
            result = self._file(
                attachment, "pdf", f"{stem}.pdf", "application/pdf"
            )
            if not result.content.startswith(b"%PDF-"):
                raise ValidationError("Current Paraguay KuDE PDF is invalid for delivery.")
            return result
        if file_kind == "xml":
            attachment = self._current_attachment(document, self.XML_TYPE)
            result = self._file(
                attachment, "xml", f"{stem}.xml", "application/xml"
            )
            self._validate_final_rde(result.content, document)
            return result
        raise ValidationError("Paraguay delivery file kind is unsupported.")

    def validate_eligibility(self, *, document):
        document.ensure_one()
        self._check_access(document)
        self._validate_eligibility(document)
        return True

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
        if not self._has_authoritative_acceptance(document):
            raise ValidationError(
                "Paraguay delivery requires coherent persisted SIFEN acceptance evidence."
            )

    def _has_authoritative_acceptance(self, document):
        cdc = (document.country_identifier or document.py_cdc or "").strip()
        evidence = self.env["fiscal.transmission"].sudo().search([
            ("document_id", "=", document.id),
            ("transmission_type", "in", ("submit", "status_query")),
            ("state", "=", "accepted"),
        ])
        if not evidence:
            return False
        direct = evidence.filtered(lambda item: item.transmission_type == "submit")
        candidates = direct or evidence.filtered(
            lambda item: item.transmission_type == "status_query"
        )
        validations = [
            self._valid_acceptance_transmission(item, document=document, cdc=cdc)
            for item in candidates
        ]
        return bool(validations) and all(validations)

    def _valid_acceptance_transmission(self, transmission, *, document, cdc):
        if (
            transmission.document_id != document
            or transmission.tenant_id != document.tenant_id
            or transmission.company_id != document.company_id
            or (transmission.country_code or "").upper() != "PY"
            or transmission.environment != document.environment
            or (transmission.country_identifier or "").strip() != cdc
            or not re.fullmatch(r"[0-9a-f]{64}", transmission.request_hash or "")
            or not re.fullmatch(r"[0-9a-f]{64}", transmission.response_hash or "")
        ):
            return False
        metadata = self._metadata(transmission)
        if metadata.get("ambiguous") is True:
            return False
        if transmission.transmission_type == "submit":
            return (
                metadata.get("ambiguous") is False
                and transmission.authority_status_code
                == PySifenRecepDeResponseParser.ACCEPTED_CODE
                and document.authority_status
                == PySifenRecepDeResponseParser.ACCEPTED_CODE
            )
        return self._valid_reconciliation_evidence(
            transmission,
            document=document,
            cdc=cdc,
            metadata=metadata,
        )

    def _valid_reconciliation_evidence(
        self, transmission, *, document, cdc, metadata
    ):
        normalized = metadata.get("normalized_response")
        structure = metadata.get("response_structure")
        original_ids = metadata.get("original_submission_ids")
        if (
            transmission.authority_status_code != self.CONSULTA_APPROVED_CODE
            or document.authority_status != self.CONSULTA_APPROVED_CODE
            or metadata.get("result_category") != "approved"
            or not isinstance(normalized, dict)
            or normalized.get("approved") is not True
            or not isinstance(structure, dict)
            or structure.get("returned_cdc") != cdc
            or not isinstance(original_ids, list)
            or not original_ids
            or any(not isinstance(item, int) for item in original_ids)
        ):
            return False
        originals = self.env["fiscal.transmission"].sudo().browse(original_ids).exists()
        if len(originals) != len(set(original_ids)):
            return False
        return all(
            original.document_id == document
            and original.transmission_type == "submit"
            and original.tenant_id == document.tenant_id
            and original.company_id == document.company_id
            and (original.country_code or "").upper() == "PY"
            and original.environment == document.environment
            and (original.country_identifier or "").strip() == cdc
            for original in originals
        )

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
