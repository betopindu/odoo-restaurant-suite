import hashlib
from urllib.parse import urlencode

from lxml import etree

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)


class PyQrGenerationService:
    """Generate the Paraguay SIFEN QR payload string for a signed XML document."""

    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS
    XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
    QR_BASE_URL = "https://ekuatia.set.gov.py/consultas/qr"
    QR_VERSION = "150"
    QR_FIELD_ORDER = (
        "nVersion",
        "Id",
        "dFeEmiDE",
        "dRucRec",
        "dTotGralOpe",
        "dTotIVA",
        "cItems",
        "DigestValue",
        "IdCSC",
    )

    def generate(
        self,
        *,
        document,
        signed_xml_bytes,
        digest_value,
        cdc,
        base_url=None,
    ):
        document.ensure_one()
        digest_value = (digest_value or "").strip()
        cdc = (cdc or "").strip()
        if not digest_value:
            raise ValidationError("Paraguay QR DigestValue is required.")
        if not cdc:
            raise ValidationError("Paraguay QR CDC is required.")

        root = self._parse(signed_xml_bytes)
        values = self._extract_values(root, cdc, digest_value)
        csc = self._csc_values(document)
        values.update({
            "nVersion": self.QR_VERSION,
            "DigestValue": digest_value,
            "IdCSC": csc["id_csc"],
        })

        query_string = self._query_string(values)
        qr_hash = hashlib.sha256(
            (query_string + csc["csc_value"]).encode("utf-8")
        ).hexdigest()
        qr_string = f"{base_url or self.QR_BASE_URL}?{query_string}&cHashQR={qr_hash}"
        return {
            "qr_string": qr_string,
            "qr_hash": qr_hash,
        }

    def _parse(self, xml_content):
        try:
            if isinstance(xml_content, str):
                xml_content = xml_content.encode("utf-8")
            parser = etree.XMLParser(
                resolve_entities=False,
                load_dtd=False,
                no_network=True,
            )
            return etree.fromstring(xml_content, parser=parser)
        except (TypeError, ValueError, etree.XMLSyntaxError) as error:
            raise ValidationError("Malformed signed Paraguay XML for QR.") from error

    def _extract_values(self, root, cdc, digest_value):
        if root.tag != self._tag("rDE"):
            raise ValidationError("Paraguay QR signed XML root must be rDE.")
        de_nodes = root.findall(self._tag("DE"))
        if len(de_nodes) != 1:
            raise ValidationError("Paraguay QR signed XML must contain exactly one DE.")
        signature = self._signature(root)
        extracted_digest_value = self._digest_value(signature)
        if extracted_digest_value != digest_value:
            raise ValidationError(
                "Paraguay QR DigestValue must match signed XML DigestValue."
            )
        de = de_nodes[0]
        if (de.get("Id") or "").strip() != cdc:
            raise ValidationError("Paraguay QR CDC must match signed XML DE Id.")

        values = {
            "Id": cdc,
            "dFeEmiDE": self._required_text(de, "gDatGralOpe/dFeEmiDE"),
            "dRucRec": self._receiver_identifier(de),
            "dTotGralOpe": self._required_text(de, "gTotSub/dTotGralOpe"),
            "dTotIVA": self._required_text(de, "gTotSub/dTotIVA"),
            "cItems": str(len(de.findall(f".//{self._tag('gCamItem')}"))),
        }
        if values["cItems"] == "0":
            raise ValidationError("Paraguay QR signed XML must contain at least one item.")
        return values

    def _signature(self, root):
        signatures = [
            child
            for child in root
            if etree.QName(child).localname == "Signature"
            and child.tag == f"{{{self.XMLDSIG_NS}}}Signature"
        ]
        if len(signatures) != 1:
            raise ValidationError(
                "Paraguay QR signed XML must contain exactly one XMLDSig Signature."
            )
        return signatures[0]

    def _digest_value(self, signature):
        digest_values = signature.findall(f".//{{{self.XMLDSIG_NS}}}DigestValue")
        if len(digest_values) != 1:
            raise ValidationError(
                "Paraguay QR signed XML must contain exactly one XMLDSig DigestValue."
            )
        return (digest_values[0].text or "").strip()

    def _receiver_identifier(self, de):
        receiver_ruc = self._find_text(de, "gDatGralOpe/gDatRec/dRucRec")
        if receiver_ruc:
            return receiver_ruc
        raise ValidationError("Paraguay QR receiver RUC is required.")

    def _csc_values(self, document):
        csc = document.py_csc_id
        if not csc:
            raise ValidationError("Paraguay QR IdCSC and CSC are required.")
        id_csc = (csc.id_csc or "").strip()
        csc_value = (csc.csc_value or "").strip()
        if not id_csc or not csc_value:
            raise ValidationError("Paraguay QR IdCSC and CSC are required.")
        return {
            "id_csc": id_csc,
            "csc_value": csc_value,
        }

    def _query_string(self, values):
        missing = [field for field in self.QR_FIELD_ORDER if not values.get(field)]
        if missing:
            raise ValidationError(
                "Paraguay QR mandatory fields are missing: " + ", ".join(missing)
            )
        return urlencode([(field, values[field]) for field in self.QR_FIELD_ORDER])

    def _required_text(self, root, path):
        value = self._find_text(root, path)
        if not value:
            raise ValidationError(f"Paraguay QR mandatory field is missing: {path}.")
        return value

    def _find_text(self, root, path):
        current = root
        for name in path.split("/"):
            current = current.find(self._tag(name))
            if current is None:
                return None
        return (current.text or "").strip() or None

    def _tag(self, name):
        return f"{{{self.SIFEN_NS}}}{name}"
