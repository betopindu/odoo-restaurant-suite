from lxml import etree

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)

try:
    import xmlsec
except ImportError:  # pragma: no cover - exercised by runtime dependency tests
    xmlsec = None


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
    ):
        if xmlsec is None:
            raise ValidationError("XML security runtime is not available.")

        root = self._parse(prepared_xml_bytes)
        de = self._locate_de(root)
        cdc = (de.get("Id") or "").strip()
        if not cdc:
            raise ValidationError("Prepared Paraguay XML DE is missing Id.")
        if self._has_signature(root):
            raise ValidationError("Prepared Paraguay XML already contains Signature.")

        signature = self._build_signature_template(root, de, cdc)
        etree.indent(root, space="  ")
        self._sign_template(
            root,
            signature,
            certificate_bytes,
            private_key_bytes,
            private_key_password,
        )

        return {
            "signed_xml_bytes": etree.tostring(
                root,
                encoding="UTF-8",
                xml_declaration=True,
            ),
            "cdc": cdc,
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
            raise ValidationError("Malformed prepared Paraguay XML.") from error

    def _locate_de(self, root):
        de_nodes = root.findall(self._tag("DE"))
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
        xmlsec.template.add_transform(
            reference,
            xmlsec.constants.TransformExclC14N,
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
            xmlsec.tree.add_ids(root, ["Id"])
            key = xmlsec.Key.from_memory(
                private_key_bytes,
                xmlsec.constants.KeyDataFormatPem,
                private_key_password,
            )
            key.load_cert_from_memory(
                certificate_bytes,
                xmlsec.constants.KeyDataFormatCertPem,
            )
            context = xmlsec.SignatureContext()
            context.key = key
            context.sign(signature)
        except (TypeError, ValueError, xmlsec.Error) as error:
            raise ValidationError("Prepared Paraguay XML could not be signed.") from error

    def _tag(self, name):
        return f"{{{self.SIFEN_NS}}}{name}"
