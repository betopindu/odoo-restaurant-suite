from lxml import etree

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import PyUnsignedXmlBuilder


class PyXmlValidationService:
    """Validate Paraguay unsigned XML for pre-signature readiness.

    This is not official SIFEN XSD validation. It checks the project-owned
    structure that must be present before later signature and QR stages.
    """

    NS = {"sifen": PyUnsignedXmlBuilder.SIFEN_NS}

    REQUIRED_PATHS = [
        ("sifen:dVerFor", "format version"),
        ("sifen:DE", "DE"),
        ("sifen:DE/@Id", "DE Id"),
        ("sifen:DE/sifen:dDVId", "CDC check digit"),
        ("sifen:DE/sifen:dSisFact", "system code"),
        ("sifen:DE/sifen:gOpeDE", "electronic document operation"),
        ("sifen:DE/sifen:gTimb", "timbrado"),
        ("sifen:DE/sifen:gDatGralOpe", "general operation data"),
        ("sifen:DE/sifen:gDatGralOpe/sifen:gOpeCom", "commercial operation"),
        ("sifen:DE/sifen:gDatGralOpe/sifen:gEmis", "issuer"),
        ("sifen:DE/sifen:gDatGralOpe/sifen:gDatRec", "receiver"),
        ("sifen:DE/sifen:gDtipDE", "document type data"),
        ("sifen:DE/sifen:gDtipDE/sifen:gCamFE", "invoice data"),
        ("sifen:DE/sifen:gTotSub", "totals"),
    ]

    REPEATED_PATHS = [
        ("sifen:DE/sifen:gDatGralOpe/sifen:gEmis/sifen:gActEco", "issuer economic activities"),
        ("sifen:DE/sifen:gDtipDE/sifen:gCamItem", "items"),
    ]

    ABSENT_PATHS = [
        ("sifen:DE/sifen:dFecFirma", "signature timestamp"),
        (".//*[local-name()='Signature']", "digital signature"),
        ("sifen:DE/sifen:gCamFuFD", "QR data"),
        (".//*[local-name()='dCarQR']", "QR content"),
    ]

    def validate_unsigned_presignature(self, xml_content):
        root = self._parse(xml_content)
        self._validate_root(root)
        missing = []
        forbidden = []

        for path, label in self.REQUIRED_PATHS:
            if not self._path_has_value(root, path):
                missing.append(label)
        for path, label in self.REPEATED_PATHS:
            if not root.xpath(path, namespaces=self.NS):
                missing.append(label)

        self._validate_receiver_identity(root, missing)

        for path, label in self.ABSENT_PATHS:
            if root.xpath(path, namespaces=self.NS):
                forbidden.append(label)

        if missing or forbidden:
            messages = []
            if missing:
                messages.append("missing: " + "; ".join(missing))
            if forbidden:
                messages.append("forbidden unsigned-stage content: " + "; ".join(forbidden))
            raise ValidationError(
                "Paraguay unsigned XML is not pre-signature ready; "
                + " | ".join(messages)
            )
        return True

    def _parse(self, xml_content):
        try:
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            if isinstance(xml_content, str):
                xml_content = xml_content.encode("utf-8")
            return etree.fromstring(xml_content, parser=parser)
        except etree.XMLSyntaxError as error:
            raise ValidationError(f"Malformed Paraguay unsigned XML: {error}") from error

    def _validate_root(self, root):
        expected = f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}rDE"
        if root.tag != expected:
            raise ValidationError("Paraguay unsigned XML root must be rDE.")

    def _validate_receiver_identity(self, root, missing):
        receiver = root.xpath(
            "sifen:DE/sifen:gDatGralOpe/sifen:gDatRec",
            namespaces=self.NS,
        )
        if not receiver:
            return
        receiver = receiver[0]
        nature = self._first_text(receiver, "sifen:iNatRec")
        if nature == "1":
            self._require_child(missing, receiver, "sifen:iTiContRec", "receiver taxpayer type")
            self._require_child(missing, receiver, "sifen:dRucRec", "receiver RUC")
            self._require_child(missing, receiver, "sifen:dDVRec", "receiver RUC DV")
        elif nature == "2":
            self._require_child(missing, receiver, "sifen:iTipIDRec", "receiver ID type")
            self._require_child(missing, receiver, "sifen:dDTipIDRec", "receiver ID type description")
            self._require_child(missing, receiver, "sifen:dNumIDRec", "receiver ID number")
        else:
            missing.append("known receiver nature")

    def _require_child(self, missing, node, path, label):
        if not self._node_path_has_value(node, path):
            missing.append(label)

    def _path_has_value(self, root, path):
        result = root.xpath(path, namespaces=self.NS)
        return self._result_has_value(result)

    def _node_path_has_value(self, node, path):
        result = node.xpath(path, namespaces=self.NS)
        return self._result_has_value(result)

    def _result_has_value(self, result):
        if not result:
            return False
        first = result[0]
        if isinstance(first, str):
            return bool(first)
        return bool((first.text or "").strip()) or len(first) > 0

    def _first_text(self, node, path):
        result = node.xpath(path, namespaces=self.NS)
        if not result:
            return None
        return (result[0].text or "").strip()
