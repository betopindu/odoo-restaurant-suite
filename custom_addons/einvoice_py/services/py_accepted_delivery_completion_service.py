import base64
import hashlib
import json

from lxml import etree

from odoo.exceptions import ValidationError

from .py_fiscal_document_delivery_service import PyFiscalDocumentDeliveryService
from .py_kude_service import PyKudeService
from .py_qr_payload_attachment_service import PyQrPayloadAttachmentService
from .py_source_artifact_service import PySourceArtifactService
from .py_xml_signature_verification_service import (
    PyXmlSignatureVerificationService,
)
from .py_xsd_validation_service import PyXsdValidationService


class PyAcceptedDeliveryCompletionService:
    """Complete missing recipient artifacts from accepted persisted evidence."""

    SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"

    def __init__(
        self,
        env,
        *,
        delivery_service=None,
        kude_service=None,
        source_artifact_service=None,
        qr_service=None,
        signature_service=None,
        xsd_service=None,
    ):
        self.env = env
        self.delivery_service = delivery_service or PyFiscalDocumentDeliveryService(env)
        self.source_artifact_service = (
            source_artifact_service or PySourceArtifactService(env)
        )
        self.qr_service = qr_service or PyQrPayloadAttachmentService(env)
        self.kude_service = kude_service or PyKudeService(
            env,
            source_artifact_service=self.source_artifact_service,
            qr_attachment_service=self.qr_service,
        )
        self.signature_service = (
            signature_service or PyXmlSignatureVerificationService()
        )
        self.xsd_service = xsd_service or PyXsdValidationService()

    def ensure(self, *, document):
        document.ensure_one()
        self._lock(document)
        self.delivery_service.validate_eligibility(document=document)
        xml_file = self.delivery_service.resolve_file(
            document=document,
            file_kind="xml",
        )
        payload_attachment, payload = self.source_artifact_service.read_current_payload(
            document=document
        )
        unsigned_attachment, _unsigned = (
            self.source_artifact_service.read_current_unsigned_xml(
                document=document,
                payload_attachment=payload_attachment,
            )
        )
        signed_attachment = self._unique_current_attachment(
            document, "paraguay_xml_signed"
        )
        qr_attachment, qr_payload = self.qr_service.read_current(document=document)
        if qr_attachment != self._unique_current_attachment(
            document, "paraguay_qr_payload"
        ):
            raise ValidationError("Accepted Paraguay QR lifecycle is inconsistent.")
        rde_attachment = self.env["fiscal.attachment"].sudo().browse(
            xml_file.fiscal_attachment_id
        ).exists()
        self._validate_chain(
            document=document,
            payload_attachment=payload_attachment,
            unsigned_attachment=unsigned_attachment,
            signed_attachment=signed_attachment,
            qr_attachment=qr_attachment,
            qr_payload=qr_payload,
            rde_attachment=rde_attachment,
            rde_bytes=xml_file.content,
        )
        result = self.kude_service.generate(document=document)
        if (
            result.cdc != self._cdc(document)
            or result.payload_attachment_id != payload_attachment.id
            or result.qr_attachment_id != qr_attachment.id
        ):
            raise ValidationError(
                "Authoritative Paraguay KuDE provenance is inconsistent."
            )
        self.delivery_service.resolve_file(document=document, file_kind="pdf")
        return result

    def _validate_chain(
        self,
        *,
        document,
        payload_attachment,
        unsigned_attachment,
        signed_attachment,
        qr_attachment,
        qr_payload,
        rde_attachment,
        rde_bytes,
    ):
        if not signed_attachment or not rde_attachment:
            raise ValidationError("Accepted Paraguay artifact chain is incomplete.")
        self._validate_attachment(document, signed_attachment, "paraguay_xml_signed")
        self._validate_attachment(document, qr_attachment, "paraguay_qr_payload")
        self._validate_attachment(document, rde_attachment, "paraguay_rde_final")
        unsigned_metadata = self._metadata(unsigned_attachment)
        signed_metadata = self._metadata(signed_attachment)
        qr_metadata = self._metadata(qr_attachment)
        rde_metadata = self._metadata(rde_attachment)
        if (
            unsigned_metadata.get("payload_attachment_id") != payload_attachment.id
            or unsigned_metadata.get("payload_sha256") != payload_attachment.sha256
            or signed_metadata.get("payload_attachment_id") != payload_attachment.id
            or signed_metadata.get("payload_sha256") != payload_attachment.sha256
            or signed_metadata.get("unsigned_attachment_id") != unsigned_attachment.id
            or signed_metadata.get("unsigned_sha256") != unsigned_attachment.sha256
            or qr_metadata.get("signed_attachment_id") != signed_attachment.id
            or qr_metadata.get("signed_xml_sha256") != signed_attachment.sha256
            or rde_metadata.get("signed_attachment_id") != signed_attachment.id
            or rde_metadata.get("signed_xml_sha256") != signed_attachment.sha256
            or rde_metadata.get("qr_attachment_id") != qr_attachment.id
            or rde_metadata.get("qr_sha256") != qr_attachment.sha256
        ):
            raise ValidationError("Accepted Paraguay artifact provenance is inconsistent.")
        try:
            root = etree.fromstring(
                rde_bytes,
                etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True),
            )
        except etree.XMLSyntaxError:
            raise ValidationError("Accepted Paraguay final rDE is malformed.") from None
        de = root.find(f"{{{self.SIFEN_NS}}}DE")
        qr = root.find(
            f"{{{self.SIFEN_NS}}}gCamFuFD/{{{self.SIFEN_NS}}}dCarQR"
        )
        if (
            de is None
            or de.get("Id") != self._cdc(document)
            or qr is None
            or (qr.text or "").strip() != qr_payload.strip()
        ):
            raise ValidationError("Accepted Paraguay final rDE identity is inconsistent.")
        if not self.signature_service.verify(
            signed_xml_bytes=rde_bytes,
            expected_cdc=self._cdc(document),
        ).get("valid"):
            raise ValidationError("Accepted Paraguay final rDE signature is invalid.")
        if not self.xsd_service.validate_final_signed_xml(rde_bytes).get("valid"):
            raise ValidationError("Accepted Paraguay final rDE is not XSD v150 valid.")

    def _validate_attachment(self, document, attachment, attachment_type):
        if (
            attachment.document_id != document
            or attachment.tenant_id != document.tenant_id
            or attachment.company_id != document.company_id
            or attachment.attachment_type != attachment_type
            or not attachment.ir_attachment_id
        ):
            raise ValidationError("Accepted Paraguay artifact scope is inconsistent.")
        try:
            content = base64.b64decode(
                attachment.ir_attachment_id.datas or b"", validate=True
            )
        except (TypeError, ValueError):
            raise ValidationError("Accepted Paraguay artifact content is invalid.") from None
        if hashlib.sha256(content).hexdigest() != attachment.sha256:
            raise ValidationError("Accepted Paraguay artifact integrity check failed.")
        if self._metadata(attachment).get("artifact_status") != "current":
            raise ValidationError("Accepted Paraguay artifact is not current.")

    def _unique_current_attachment(self, document, attachment_type):
        attachments = self.env["fiscal.attachment"].sudo().search([
            ("document_id", "=", document.id),
            ("tenant_id", "=", document.tenant_id.id),
            ("company_id", "=", document.company_id.id),
            ("attachment_type", "=", attachment_type),
        ])
        current = attachments.filtered(
            lambda item: self._metadata(item).get("artifact_status") == "current"
        )
        if len(current) != 1:
            raise ValidationError(
                "Accepted Paraguay artifact lifecycle is inconsistent."
            )
        return current

    def _lock(self, document):
        self.env.cr.execute(
            "SELECT id FROM fiscal_document WHERE id = %s FOR UPDATE",
            [document.id],
        )
        if not self.env.cr.fetchone():
            raise ValidationError("Accepted Paraguay fiscal document no longer exists.")

    def _metadata(self, record):
        try:
            value = json.loads(record.metadata_json or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _cdc(self, document):
        return (document.country_identifier or document.py_cdc or "").strip()
