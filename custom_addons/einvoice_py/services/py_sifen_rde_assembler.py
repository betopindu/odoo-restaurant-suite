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
class PySifenXsdValidationError:
    message: str
    line: int | None = None
    column: int | None = None
    element: str | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class PySifenRdeAssemblyResult:
    final_xml_bytes: bytes
    xml_document: object
    xsd_valid: bool
    validation_errors: tuple
    cdc: str
    qr_url: str


class PySifenRdeAssembler:
    """Append QR content to signed Paraguay XML and validate the final rDE."""

    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS
    XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"

    def __init__(self, xsd_validation_service=None):
        self.xsd_validation_service = (
            xsd_validation_service
            if xsd_validation_service is not None
            else PyXsdValidationService()
        )

    def assemble(
        self,
        *,
        signed_xml_bytes,
        gcamfufd_xml_bytes,
        cdc,
        qr_url,
    ):
        cdc = (cdc or "").strip()
        qr_url = (qr_url or "").strip()
        if not cdc:
            raise ValidationError("Final Paraguay rDE CDC is required.")
        if not qr_url:
            raise ValidationError("Final Paraguay rDE QR URL is required.")

        root = self._parse(
            signed_xml_bytes,
            "Malformed signed Paraguay XML for final rDE.",
        )
        self._validate_signed_root(root, cdc)
        qr_group = self._parse(
            gcamfufd_xml_bytes,
            "Malformed Paraguay gCamFuFD for final rDE.",
        )
        self._validate_qr_group(qr_group, qr_url)
        root.append(qr_group)
        self._validate_final_order(root)

        final_xml_bytes = etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
        )
        report = self.xsd_validation_service.validate_final_signed_xml(
            final_xml_bytes
        )
        errors = tuple(
            PySifenXsdValidationError(
                message=entry.get("message") or "",
                line=entry.get("line"),
                column=entry.get("column"),
                element=entry.get("failing_element"),
                path=entry.get("path") or entry.get("failing_element"),
            )
            for entry in report.get("errors", [])
        )
        return PySifenRdeAssemblyResult(
            final_xml_bytes=final_xml_bytes,
            xml_document=root,
            xsd_valid=bool(report.get("valid")) and not errors,
            validation_errors=errors,
            cdc=cdc,
            qr_url=qr_url,
        )

    def _parse(self, xml_content, message):
        try:
            if isinstance(xml_content, str):
                xml_content = xml_content.encode("utf-8")
            parser = etree.XMLParser(
                resolve_entities=False,
                load_dtd=False,
                no_network=True,
            )
            return etree.fromstring(xml_content, parser)
        except (TypeError, ValueError, etree.XMLSyntaxError):
            raise ValidationError(message) from None

    def _validate_signed_root(self, root, cdc):
        if root.tag != self._tag("rDE"):
            raise ValidationError(
                "Final Paraguay XML root must be rDE."
            )
        children = list(root)
        expected = [
            self._tag("dVerFor"),
            self._tag("DE"),
            f"{{{self.XMLDSIG_NS}}}Signature",
        ]
        if [child.tag for child in children] != expected:
            raise ValidationError(
                "Signed Paraguay rDE must contain dVerFor, DE, and Signature in order."
            )
        if (children[0].text or "").strip() != "150":
            raise ValidationError(
                "Final Paraguay rDE version must be 150."
            )
        if (children[1].get("Id") or "").strip() != cdc:
            raise ValidationError(
                "Final Paraguay rDE CDC must match DE Id."
            )

    def _validate_qr_group(self, group, qr_url):
        if group.tag != self._tag("gCamFuFD"):
            raise ValidationError(
                "Final Paraguay rDE requires gCamFuFD."
            )
        children = list(group)
        if (
            len(children) != 1
            or children[0].tag != self._tag("dCarQR")
            or (children[0].text or "").strip() != qr_url
        ):
            raise ValidationError(
                "Final Paraguay rDE requires matching dCarQR content."
            )

    def _validate_final_order(self, root):
        expected = [
            self._tag("dVerFor"),
            self._tag("DE"),
            f"{{{self.XMLDSIG_NS}}}Signature",
            self._tag("gCamFuFD"),
        ]
        if [child.tag for child in root] != expected:
            raise ValidationError(
                "Final Paraguay rDE element order is invalid."
            )

    def _tag(self, name):
        return f"{{{self.SIFEN_NS}}}{name}"
