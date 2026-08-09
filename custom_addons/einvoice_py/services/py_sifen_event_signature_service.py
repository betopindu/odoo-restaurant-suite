from dataclasses import dataclass

from lxml import etree
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_xml_signature_service import (
    PyXmlSignatureService,
    xmlsec,
)


@dataclass(frozen=True, slots=True)
class PySifenEventSignatureResult:
    signed_xml_bytes: bytes
    event_id: str
    request_hash_input: bytes


class PySifenEventSignatureService:
    """Sign exactly one SIFEN rEve without changing the DE signer contract."""

    XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"

    def __init__(self, identity_validator=None):
        self.identity_validator = identity_validator or PyXmlSignatureService()

    def sign(self, *, event_xml_bytes, certificate_bytes, private_key_bytes, private_key_password=None):
        if xmlsec is None:
            raise ValidationError("XML security runtime is not available.")
        root = self._parse(event_xml_bytes)
        events = [node for node in root.iter() if etree.QName(node).localname == "rEve"]
        if len(events) != 1:
            raise ValidationError("SIFEN event XML must contain exactly one rEve.")
        event = events[0]
        event_id = (event.get("Id") or "").strip()
        if not event_id.isdigit() or not 1 <= len(event_id) <= 10:
            raise ValidationError("SIFEN event rEve Id must contain 1 to 10 digits.")
        if any(etree.QName(node).localname == "Signature" for node in root.iter()):
            raise ValidationError("SIFEN event XML is already signed.")
        self.identity_validator._validate_signing_identity(
            certificate_bytes=certificate_bytes,
            private_key_bytes=private_key_bytes,
            private_key_password=private_key_password,
        )
        signature = xmlsec.template.create(
            root,
            c14n_method=xmlsec.constants.TransformInclC14N,
            sign_method=xmlsec.constants.TransformRsaSha256,
        )
        reference = xmlsec.template.add_reference(
            signature, xmlsec.constants.TransformSha256, uri=f"#{event_id}"
        )
        xmlsec.template.add_transform(reference, xmlsec.constants.TransformEnveloped)
        key_info = xmlsec.template.ensure_key_info(signature)
        x509_data = xmlsec.template.add_x509_data(key_info)
        xmlsec.template.x509_data_add_certificate(x509_data)
        event.getparent().insert(event.getparent().index(event) + 1, signature)
        self.identity_validator._sign_template(
            root, signature, certificate_bytes, private_key_bytes, private_key_password
        )
        signed = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
        return PySifenEventSignatureResult(signed, event_id, event_xml_bytes)

    def _parse(self, value):
        try:
            parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
            return etree.fromstring(value, parser=parser)
        except (TypeError, ValueError, etree.XMLSyntaxError):
            raise ValidationError("Malformed SIFEN event XML.") from None
