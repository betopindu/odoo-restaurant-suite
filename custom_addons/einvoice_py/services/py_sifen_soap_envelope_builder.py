from dataclasses import dataclass

from lxml import etree

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)
from odoo.addons.einvoice_py.services.py_xsd_validation_service import (
    PyXsdValidationService,
)


@dataclass(frozen=True, slots=True)
class PySifenSoapEnvelopeResult:
    soap_xml_bytes: bytes
    xml_document: object
    soap_action: str | None
    service_name: str
    cdc: str
    submission_id: str


class PySifenSoapEnvelopeBuilder:
    """Wrap one validated Paraguay rDE in the synchronous SOAP 1.2 request."""

    SOAP_ENV_NS = "http://www.w3.org/2003/05/soap-envelope"
    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS
    XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
    SERVICE_NAME = "siRecepDE"
    SOAP_ACTION = None

    def __init__(self, xsd_validation_service=None):
        self.xsd_validation_service = (
            xsd_validation_service
            if xsd_validation_service is not None
            else PyXsdValidationService()
        )

    def build(self, *, validated_rde_bytes, submission_id, soap_action=None):
        root = self._parse(validated_rde_bytes)
        cdc = self._validate_rde(root)
        self._validate_submission_id(submission_id)

        report = self.xsd_validation_service.validate_final_signed_xml(
            validated_rde_bytes
        )
        if not report.get("valid"):
            raise ValidationError(
                "Final Paraguay rDE must pass local SIFEN XSD validation "
                "before SOAP assembly."
            )

        envelope = etree.Element(
            f"{{{self.SOAP_ENV_NS}}}Envelope",
            nsmap={None: self.SOAP_ENV_NS},
        )
        body = etree.SubElement(
            envelope,
            f"{{{self.SOAP_ENV_NS}}}Body",
        )
        request_node = etree.SubElement(
            body,
            f"{{{self.SIFEN_NS}}}rEnviDe",
            nsmap={None: self.SIFEN_NS},
        )
        etree.SubElement(
            request_node,
            f"{{{self.SIFEN_NS}}}dId",
        ).text = submission_id
        document_node = etree.SubElement(
            request_node,
            f"{{{self.SIFEN_NS}}}xDE",
        )
        document_node.append(root)

        soap_xml_bytes = etree.tostring(
            envelope,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )
        return PySifenSoapEnvelopeResult(
            soap_xml_bytes=soap_xml_bytes,
            xml_document=envelope,
            soap_action=(
                soap_action if soap_action is not None else self.SOAP_ACTION
            ),
            service_name=self.SERVICE_NAME,
            cdc=cdc,
            submission_id=submission_id,
        )

    def _parse(self, xml_content):
        try:
            if isinstance(xml_content, str):
                xml_content = xml_content.encode("utf-8")
            parser = etree.XMLParser(
                resolve_entities=False,
                load_dtd=False,
                no_network=True,
                remove_blank_text=False,
            )
            return etree.fromstring(xml_content, parser)
        except (TypeError, ValueError, etree.XMLSyntaxError):
            raise ValidationError(
                "Malformed final Paraguay rDE for SOAP assembly."
            ) from None

    def _validate_rde(self, root):
        if root.tag != f"{{{self.SIFEN_NS}}}rDE":
            raise ValidationError(
                "SIFEN SOAP assembly requires a final Paraguay rDE."
            )
        de_nodes = root.findall(f"{{{self.SIFEN_NS}}}DE")
        if len(de_nodes) != 1:
            raise ValidationError(
                "Final Paraguay rDE must contain exactly one DE."
            )
        cdc = (de_nodes[0].get("Id") or "").strip()
        if not cdc:
            raise ValidationError(
                "Final Paraguay rDE DE Id CDC is required."
            )
        signatures = root.findall(f"{{{self.XMLDSIG_NS}}}Signature")
        if len(signatures) != 1:
            raise ValidationError(
                "Final Paraguay rDE must contain exactly one XMLDSig Signature."
            )
        qr_nodes = root.findall(
            f"{{{self.SIFEN_NS}}}gCamFuFD/"
            f"{{{self.SIFEN_NS}}}dCarQR"
        )
        if len(qr_nodes) != 1 or not (qr_nodes[0].text or "").strip():
            raise ValidationError(
                "Final Paraguay rDE must contain gCamFuFD/dCarQR."
            )
        return cdc

    def _validate_submission_id(self, submission_id):
        if (
            not isinstance(submission_id, str)
            or not submission_id.isdigit()
            or not 1 <= len(submission_id) <= 15
        ):
            raise ValidationError(
                "SIFEN SOAP submission identifier must contain 1 to 15 digits."
            )
