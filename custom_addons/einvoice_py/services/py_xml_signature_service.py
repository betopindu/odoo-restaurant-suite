import base64
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from lxml import etree

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)

try:
    import xmlsec
except ImportError:  # pragma: no cover - exercised by runtime dependency tests
    xmlsec = None


@dataclass(frozen=True, slots=True)
class PyXmlSignatureResult(Mapping):
    signed_xml_bytes: bytes
    cdc: str
    reference_uri: str
    digest_value: str
    signature_value: str
    certificate_der_base64: str

    def __getitem__(self, key):
        try:
            return getattr(self, key)
        except (AttributeError, TypeError):
            raise KeyError(key) from None

    def __iter__(self):
        return iter(self.__dataclass_fields__)

    def __len__(self):
        return len(self.__dataclass_fields__)


class PyXmlSignatureService:
    """Generate an enveloped XMLDSig signature for prepared Paraguay XML."""

    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS
    XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"

    def sign(
        self,
        *,
        prepared_xml_bytes,
        certificate_bytes,
        private_key_bytes,
        private_key_password=None,
        cdc=None,
    ):
        if xmlsec is None:
            raise ValidationError("XML security runtime is not available.")

        root = self._parse(prepared_xml_bytes)
        de = self._locate_de(root)
        xml_cdc = (de.get("Id") or "").strip()
        if not xml_cdc:
            raise ValidationError("Prepared Paraguay XML DE is missing Id.")
        supplied_cdc = (cdc or xml_cdc).strip()
        if supplied_cdc != xml_cdc:
            raise ValidationError(
                "Prepared Paraguay XML DE Id must match the supplied CDC."
            )
        if self._has_signature(root):
            raise ValidationError("Prepared Paraguay XML already contains Signature.")

        certificate_der_base64 = self._validate_signing_identity(
            certificate_bytes=certificate_bytes,
            private_key_bytes=private_key_bytes,
            private_key_password=private_key_password,
        )
        signature = self._build_signature_template(root, de, xml_cdc)
        etree.indent(root, space="  ")
        self._sign_template(
            root,
            signature,
            certificate_bytes,
            private_key_bytes,
            private_key_password,
        )

        signed_xml_bytes = etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
        )
        return PyXmlSignatureResult(
            signed_xml_bytes=signed_xml_bytes,
            cdc=xml_cdc,
            reference_uri=self._signature_text(
                signature,
                "Reference",
                attribute="URI",
            ),
            digest_value=self._signature_text(signature, "DigestValue"),
            signature_value=self._signature_text(signature, "SignatureValue"),
            certificate_der_base64=certificate_der_base64,
        )

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
        except (TypeError, ValueError, etree.XMLSyntaxError):
            raise ValidationError("Malformed prepared Paraguay XML.") from None

    def _locate_de(self, root):
        de_nodes = list(root.iter(self._tag("DE")))
        if len(de_nodes) != 1:
            raise ValidationError("Prepared Paraguay XML must contain exactly one DE.")
        return de_nodes[0]

    def _has_signature(self, root):
        return any(
            etree.QName(node).localname == "Signature"
            for node in root.iter()
        )

    def _build_signature_template(self, root, de, cdc):
        signature = xmlsec.template.create(
            root,
            c14n_method=xmlsec.constants.TransformInclC14N,
            sign_method=xmlsec.constants.TransformRsaSha256,
        )
        reference = xmlsec.template.add_reference(
            signature,
            xmlsec.constants.TransformSha256,
            uri=f"#{cdc}",
        )
        xmlsec.template.add_transform(
            reference,
            xmlsec.constants.TransformEnveloped,
        )
        key_info = xmlsec.template.ensure_key_info(signature)
        x509_data = xmlsec.template.add_x509_data(key_info)
        xmlsec.template.x509_data_add_certificate(x509_data)

        children = list(root)
        root.insert(children.index(de) + 1, signature)
        return signature

    def _sign_template(
        self,
        root,
        signature,
        certificate_bytes,
        private_key_bytes,
        private_key_password,
    ):
        try:
            xmlsec_password = private_key_password
            if isinstance(xmlsec_password, bytes):
                xmlsec_password = xmlsec_password.decode("utf-8")
            xmlsec.tree.add_ids(root, ["Id"])
            key = xmlsec.Key.from_memory(
                private_key_bytes,
                xmlsec.constants.KeyDataFormatPem,
                xmlsec_password,
            )
            key.load_cert_from_memory(
                certificate_bytes,
                xmlsec.constants.KeyDataFormatCertPem,
            )
            context = xmlsec.SignatureContext()
            context.key = key
            context.sign(signature)
        except (TypeError, ValueError, xmlsec.Error):
            raise ValidationError(
                "Prepared Paraguay XML could not be signed."
            ) from None

    def _validate_signing_identity(
        self,
        *,
        certificate_bytes,
        private_key_bytes,
        private_key_password,
    ):
        try:
            password = private_key_password
            if isinstance(password, str):
                password = password.encode("utf-8")
            certificate = x509.load_pem_x509_certificate(
                certificate_bytes
            )
            private_key = serialization.load_pem_private_key(
                private_key_bytes,
                password=password,
            )
        except (TypeError, ValueError):
            raise ValidationError(
                "Paraguay XML signing identity is invalid."
            ) from None
        certificate_key = certificate.public_key()
        if not isinstance(private_key, rsa.RSAPrivateKey) or not isinstance(
            certificate_key,
            rsa.RSAPublicKey,
        ):
            raise ValidationError(
                "Paraguay XML signing requires an RSA identity."
            )
        if private_key.public_key().public_numbers() != (
            certificate_key.public_numbers()
        ):
            raise ValidationError(
                "Paraguay XML signing certificate and private key do not match."
            )
        return base64.b64encode(
            certificate.public_bytes(serialization.Encoding.DER)
        ).decode("ascii")

    def _signature_text(self, signature, name, attribute=None):
        node = signature.find(f".//{{{self.XMLDSIG_NS}}}{name}")
        if node is None:
            raise ValidationError(
                "Prepared Paraguay XML signature result is incomplete."
            )
        value = node.get(attribute) if attribute else node.text
        value = (value or "").strip()
        if not value:
            raise ValidationError(
                "Prepared Paraguay XML signature result is incomplete."
            )
        return value

    def _tag(self, name):
        return f"{{{self.SIFEN_NS}}}{name}"
