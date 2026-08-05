from lxml import etree

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_datetime_service import (
    PySifenDatetimeService,
)
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)


class PySignedXmlPreparationService:
    """Prepare unsigned Paraguay XML for a later XMLDSig stage."""

    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS

    def prepare(self, document, unsigned_xml_bytes, signing_timestamp):
        document.ensure_one()
        root = self._parse(unsigned_xml_bytes)
        if root.tag != self._tag("rDE"):
            raise ValidationError(
                "Paraguay unsigned XML root must be rDE in the official SIFEN namespace."
            )

        de_nodes = root.findall(self._tag("DE"))
        if len(de_nodes) != 1:
            raise ValidationError(
                "Paraguay unsigned XML must contain exactly one DE."
            )
        de = de_nodes[0]

        forbidden_names = {"Signature", "gCamFuFD", "dCarQR"}
        if any(
            etree.QName(node).localname in forbidden_names
            for node in root.iter()
        ):
            raise ValidationError(
                "Paraguay unsigned XML contains signing or QR-stage content."
            )

        xml_cdc = (de.get("Id") or "").strip()
        if not xml_cdc:
            raise ValidationError("Paraguay unsigned XML DE is missing Id.")

        document_cdc = (document.py_cdc or "").strip()
        country_identifier = (document.country_identifier or "").strip()
        if not document_cdc:
            raise ValidationError("Paraguay fiscal document CDC is required before signing.")
        if country_identifier != document_cdc:
            raise ValidationError(
                "Paraguay fiscal document CDC and country identifier must match."
            )
        if xml_cdc != document_cdc:
            raise ValidationError(
                "Paraguay unsigned XML DE Id must match the fiscal document CDC."
            )

        check_digit_nodes = de.findall(self._tag("dDVId"))
        if len(check_digit_nodes) != 1:
            raise ValidationError(
                "Paraguay unsigned XML DE must contain exactly one dDVId."
            )
        check_digit = check_digit_nodes[0]
        if not (check_digit.text or "").strip():
            raise ValidationError("Paraguay unsigned XML DE has an empty dDVId.")
        stored_check_digit = (document.py_cdc_dv or "").strip()
        expected_check_digit = document_cdc[-1:]
        if stored_check_digit != expected_check_digit:
            raise ValidationError(
                "Paraguay fiscal document CDC check digit is inconsistent."
            )
        if (check_digit.text or "").strip() != expected_check_digit:
            raise ValidationError(
                "Paraguay unsigned XML dDVId must match the fiscal document CDC."
            )

        if de.find(self._tag("dFecFirma")) is not None:
            raise ValidationError("Paraguay unsigned XML already contains dFecFirma.")

        system_code_nodes = de.findall(self._tag("dSisFact"))
        if len(system_code_nodes) != 1:
            raise ValidationError(
                "Paraguay unsigned XML DE must contain exactly one dSisFact."
            )
        system_code = system_code_nodes[0]

        signing_time = self._format_signing_timestamp(signing_timestamp)
        children = list(de)
        check_digit_index = children.index(check_digit)
        signature_time = etree.Element(self._tag("dFecFirma"))
        signature_time.text = signing_time
        de.insert(check_digit_index + 1, signature_time)

        if list(de).index(system_code) <= list(de).index(signature_time):
            raise ValidationError(
                "Paraguay unsigned XML dSisFact must remain after dFecFirma."
            )

        etree.indent(root, space="  ")
        prepared_xml_bytes = etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
        )
        return {
            "prepared_xml_bytes": prepared_xml_bytes,
            "cdc": document_cdc,
            "signing_time": signing_time,
        }

    def _parse(self, xml_content):
        try:
            if isinstance(xml_content, str):
                xml_content = xml_content.encode("utf-8")
            parser = etree.XMLParser(
                resolve_entities=False,
                load_dtd=False,
                no_network=True,
                remove_blank_text=True,
            )
            return etree.fromstring(xml_content, parser=parser)
        except (TypeError, ValueError, etree.XMLSyntaxError) as error:
            raise ValidationError("Malformed Paraguay unsigned XML.") from error

    def _format_signing_timestamp(self, signing_timestamp):
        if signing_timestamp in (None, False, ""):
            raise ValidationError("Paraguay signing timestamp is required.")
        return PySifenDatetimeService.format_fiscal_datetime(
            signing_timestamp,
            field_label="Paraguay signing timestamp",
        )

    def _tag(self, name):
        return f"{{{self.SIFEN_NS}}}{name}"
