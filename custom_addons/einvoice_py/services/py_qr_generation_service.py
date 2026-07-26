import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from lxml import etree

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)


@dataclass(frozen=True, slots=True)
class PySifenQrResult(Mapping):
    qr_string: str
    parameters_string: str
    qr_hash: str
    gcamfufd_xml_bytes: bytes
    environment: str

    @property
    def raw_qr_url(self):
        return self.qr_string

    @property
    def generated_gcamfufd(self):
        return self.gcamfufd_xml_bytes

    def __getitem__(self, key):
        try:
            return getattr(self, key)
        except (AttributeError, TypeError):
            raise KeyError(key) from None

    def __iter__(self):
        return iter(self.__dataclass_fields__)

    def __len__(self):
        return len(self.__dataclass_fields__)


class PySifenQrBuilder:
    """Build deterministic Paraguay v150 QR data from an already signed DE."""

    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS
    XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
    QR_VERSION = "150"
    QR_BASE_URLS = {
        "test": "https://ekuatia.set.gov.py/consultas-test/qr",
        "production": "https://ekuatia.set.gov.py/consultas/qr",
    }
    def build(
        self,
        *,
        signed_xml_bytes,
        cdc,
        digest_value,
        csc_id,
        csc_secret,
        environment,
        base_url=None,
    ):
        cdc = (cdc or "").strip()
        digest_value = (digest_value or "").strip()
        csc_id = (csc_id or "").strip()
        environment = (environment or "").strip().lower()
        if not cdc:
            raise ValidationError("Paraguay QR CDC is required.")
        if not cdc.isdigit() or len(cdc) != 44:
            raise ValidationError(
                "Paraguay QR CDC must contain exactly 44 digits."
            )
        if not digest_value:
            raise ValidationError("Paraguay QR DigestValue is required.")
        if not csc_id.isdigit() or len(csc_id) != 4:
            raise ValidationError(
                "Paraguay QR IdCSC must contain exactly four digits."
            )
        if not isinstance(csc_secret, str) or not csc_secret:
            raise ValidationError("Paraguay QR CSC secret is required.")
        if environment not in self.QR_BASE_URLS:
            raise ValidationError(
                "Paraguay QR environment must be TEST or PRODUCTION."
            )

        root = self._parse(signed_xml_bytes)
        values = self._extract_values(root, cdc, digest_value)
        receiver_name, receiver_value = values.pop("receiver_identifier")
        ordered_values = {
            "nVersion": self.QR_VERSION,
            "Id": cdc,
            "dFeEmiDE": self._hex_text(values["dFeEmiDE"]),
            receiver_name: receiver_value,
            "dTotGralOpe": values["dTotGralOpe"],
            "dTotIVA": values["dTotIVA"],
            "cItems": values["cItems"],
            "DigestValue": self._hex_text(digest_value),
            "IdCSC": csc_id,
        }
        parameter_order = (
            "nVersion",
            "Id",
            "dFeEmiDE",
            receiver_name,
            "dTotGralOpe",
            "dTotIVA",
            "cItems",
            "DigestValue",
            "IdCSC",
        )
        parameters_string = "&".join(
            f"{name}={ordered_values[name]}" for name in parameter_order
        )
        qr_hash = hashlib.sha256(
            (parameters_string + csc_secret).encode("utf-8")
        ).hexdigest()
        qr_string = (
            f"{base_url or self.QR_BASE_URLS[environment]}"
            f"?{parameters_string}&cHashQR={qr_hash}"
        )
        return PySifenQrResult(
            qr_string=qr_string,
            parameters_string=parameters_string,
            qr_hash=qr_hash,
            gcamfufd_xml_bytes=self._gcamfufd(qr_string),
            environment=environment,
        )

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
        except (TypeError, ValueError, etree.XMLSyntaxError):
            raise ValidationError(
                "Malformed signed Paraguay XML for QR."
            ) from None

    def _extract_values(self, root, cdc, digest_value):
        if root.tag != self._tag("rDE"):
            raise ValidationError("Paraguay QR signed XML root must be rDE.")
        de_nodes = list(root.iter(self._tag("DE")))
        if len(de_nodes) != 1:
            raise ValidationError(
                "Paraguay QR signed XML must contain exactly one DE."
            )
        signature = self._signature(root)
        extracted_digest_value = self._digest_value(signature)
        if extracted_digest_value != digest_value:
            raise ValidationError(
                "Paraguay QR DigestValue must match signed XML DigestValue."
            )
        de = de_nodes[0]
        if (de.get("Id") or "").strip() != cdc:
            raise ValidationError(
                "Paraguay QR CDC must match signed XML DE Id."
            )

        values = {
            "dFeEmiDE": self._required_text(
                de,
                "gDatGralOpe/dFeEmiDE",
            ),
            "receiver_identifier": self._receiver_identifier(de),
            "dTotGralOpe": self._required_text(
                de,
                "gTotSub/dTotGralOpe",
            ),
            "dTotIVA": self._required_text(de, "gTotSub/dTotIVA"),
            "cItems": str(
                len(de.findall(f".//{self._tag('gCamItem')}"))
            ),
        }
        if values["cItems"] == "0":
            raise ValidationError(
                "Paraguay QR signed XML must contain at least one item."
            )
        return values

    def _signature(self, root):
        signatures = root.findall(f"{{{self.XMLDSIG_NS}}}Signature")
        if len(signatures) != 1:
            raise ValidationError(
                "Paraguay QR signed XML must contain exactly one XMLDSig Signature."
            )
        return signatures[0]

    def _digest_value(self, signature):
        digest_values = signature.findall(
            f".//{{{self.XMLDSIG_NS}}}DigestValue"
        )
        if len(digest_values) != 1:
            raise ValidationError(
                "Paraguay QR signed XML must contain exactly one XMLDSig DigestValue."
            )
        value = (digest_values[0].text or "").strip()
        if not value:
            raise ValidationError(
                "Paraguay QR signed XML DigestValue is missing."
            )
        return value

    def _receiver_identifier(self, de):
        receiver_ruc = self._find_text(
            de,
            "gDatGralOpe/gDatRec/dRucRec",
        )
        receiver_document = self._find_text(
            de,
            "gDatGralOpe/gDatRec/dNumIDRec",
        )
        if bool(receiver_ruc) == bool(receiver_document):
            raise ValidationError(
                "Paraguay QR requires exactly one receiver identifier."
            )
        if receiver_ruc:
            return "dRucRec", receiver_ruc
        return "dNumIDRec", receiver_document

    def _gcamfufd(self, qr_string):
        group = etree.Element(self._tag("gCamFuFD"))
        etree.SubElement(group, self._tag("dCarQR")).text = qr_string
        return etree.tostring(group, encoding="UTF-8")

    def _hex_text(self, value):
        return value.encode("utf-8").hex()

    def _required_text(self, root, path):
        value = self._find_text(root, path)
        if not value:
            raise ValidationError(
                f"Paraguay QR mandatory field is missing: {path}."
            )
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


class PyQrGenerationService(PySifenQrBuilder):
    """Backward-compatible document adapter for the SIFEN QR builder."""

    QR_BASE_URL = PySifenQrBuilder.QR_BASE_URLS["production"]

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
        csc = document.py_csc_id
        if not csc:
            raise ValidationError("Paraguay QR IdCSC and CSC are required.")
        csc_id = (csc.id_csc or "").strip()
        csc_secret = (csc.csc_value or "").strip()
        if not csc_id or not csc_secret:
            raise ValidationError("Paraguay QR IdCSC and CSC are required.")
        return self.build(
            signed_xml_bytes=signed_xml_bytes,
            cdc=cdc,
            digest_value=digest_value,
            csc_id=csc_id,
            csc_secret=csc_secret,
            environment=document.environment,
            base_url=base_url,
        )


SifenQrBuilder = PySifenQrBuilder
