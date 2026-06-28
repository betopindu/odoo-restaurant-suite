from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
import xmlsec

from odoo.exceptions import ValidationError
from odoo.tests.common import BaseCase

from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)
from odoo.addons.einvoice_py.services.py_xml_signature_service import (
    PyXmlSignatureService,
)


class TestPyXmlSignatureService(BaseCase):
    CDC = "01444444017001001001452822017012515873260988"
    SIGNING_TIME = "2026-06-18T12:34:56"
    XMLDSIG_NS = PyXmlSignatureService.XMLDSIG_NS

    def setUp(self):
        super().setUp()
        self.service = PyXmlSignatureService()
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self.certificate = self._certificate(self.private_key)

    def _certificate(self, key):
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "XML Signature Fixture"),
        ])
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2026, 6, 18) - timedelta(days=1))
            .not_valid_after(datetime(2026, 6, 18) + timedelta(days=30))
            .sign(private_key=key, algorithm=hashes.SHA256())
        )

    def _certificate_bytes(self):
        return self.certificate.public_bytes(serialization.Encoding.PEM)

    def _private_key_bytes(self):
        return self.private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

    def _prepared_xml(self, *, include_de=True, cdc=None):
        namespace = PyUnsignedXmlBuilder.SIFEN_NS
        root = etree.Element(f"{{{namespace}}}rDE", nsmap={None: namespace})
        etree.SubElement(root, f"{{{namespace}}}dVerFor").text = "150"
        if include_de:
            de = etree.SubElement(
                root,
                f"{{{namespace}}}DE",
                {"Id": self.CDC if cdc is None else cdc},
            )
            etree.SubElement(de, f"{{{namespace}}}dDVId").text = self.CDC[-1]
            etree.SubElement(de, f"{{{namespace}}}dFecFirma").text = self.SIGNING_TIME
            etree.SubElement(de, f"{{{namespace}}}dSisFact").text = "1"
            etree.SubElement(de, f"{{{namespace}}}gOpeDE")
        etree.indent(root, space="  ")
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    def _sign(self, xml_content=None, **overrides):
        values = {
            "prepared_xml_bytes": xml_content or self._prepared_xml(),
            "certificate_bytes": self._certificate_bytes(),
            "private_key_bytes": self._private_key_bytes(),
        }
        values.update(overrides)
        return self.service.sign(**values)

    def _signed_root(self):
        result = self._sign()
        return etree.fromstring(result["signed_xml_bytes"])

    def _signature(self, root):
        return root.find(f"{{{self.XMLDSIG_NS}}}Signature")

    def test_valid_signature_generated(self):
        result = self._sign()
        root = etree.fromstring(result["signed_xml_bytes"])
        signature = self._signature(root)

        self.assertEqual(result["cdc"], self.CDC)
        self.assertIsNotNone(signature)
        self.assertTrue(
            root.xpath(
                "boolean(.//*[local-name()='SignatureValue' and normalize-space()])"
            )
        )
        self.assertTrue(
            root.xpath(
                "boolean(.//*[local-name()='DigestValue' and normalize-space()])"
            )
        )
        xmlsec.tree.add_ids(root, ["Id"])
        key = xmlsec.Key.from_memory(
            self._certificate_bytes(),
            xmlsec.constants.KeyDataFormatCertPem,
        )
        context = xmlsec.SignatureContext()
        context.key = key
        context.verify(signature)

    def test_signature_inserted_after_de(self):
        root = self._signed_root()

        self.assertEqual(
            [etree.QName(child).localname for child in root],
            ["dVerFor", "DE", "Signature"],
        )

    def test_dfecfirma_is_preserved_after_signing(self):
        root = self._signed_root()
        de = root.find(f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}DE")
        children = [etree.QName(child).localname for child in de]
        signing_time = de.find(f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}dFecFirma")

        self.assertIsNotNone(signing_time)
        self.assertEqual(signing_time.text, self.SIGNING_TIME)
        self.assertEqual(
            children[:3],
            ["dDVId", "dFecFirma", "dSisFact"],
        )

    def test_reference_uri_equals_cdc(self):
        root = self._signed_root()
        reference = root.find(f".//{{{self.XMLDSIG_NS}}}Reference")

        self.assertEqual(reference.get("URI"), f"#{self.CDC}")

    def test_digest_method_is_sha256(self):
        root = self._signed_root()
        digest_method = root.find(f".//{{{self.XMLDSIG_NS}}}DigestMethod")

        self.assertEqual(
            digest_method.get("Algorithm"),
            "http://www.w3.org/2001/04/xmlenc#sha256",
        )

    def test_signature_method_is_rsa_sha256(self):
        root = self._signed_root()
        signature_method = root.find(f".//{{{self.XMLDSIG_NS}}}SignatureMethod")

        self.assertEqual(
            signature_method.get("Algorithm"),
            "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
        )

    def test_canonicalization_is_inclusive_c14n(self):
        root = self._signed_root()
        canonicalization_method = root.find(
            f".//{{{self.XMLDSIG_NS}}}CanonicalizationMethod"
        )

        self.assertEqual(
            canonicalization_method.get("Algorithm"),
            "http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
        )

    def test_required_transforms_are_present(self):
        root = self._signed_root()
        transforms = [
            transform.get("Algorithm")
            for transform in root.findall(f".//{{{self.XMLDSIG_NS}}}Transform")
        ]

        self.assertEqual(
            transforms,
            [
                "http://www.w3.org/2000/09/xmldsig#enveloped-signature",
                "http://www.w3.org/2001/10/xml-exc-c14n#",
            ],
        )

    def test_x509_certificate_is_embedded(self):
        root = self._signed_root()
        embedded_certificate = root.find(f".//{{{self.XMLDSIG_NS}}}X509Certificate")

        self.assertIsNotNone(embedded_certificate)
        self.assertTrue((embedded_certificate.text or "").strip())

    def test_malformed_xml_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "Malformed prepared Paraguay XML"):
            self._sign(b"<rDE>")

    def test_missing_de_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "exactly one DE"):
            self._sign(self._prepared_xml(include_de=False))

    def test_multiple_de_is_rejected(self):
        root = etree.fromstring(self._prepared_xml())
        etree.SubElement(
            root,
            f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}DE",
            {"Id": self.CDC},
        )

        with self.assertRaisesRegex(ValidationError, "exactly one DE"):
            self._sign(etree.tostring(root))

    def test_missing_cdc_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "DE is missing Id"):
            self._sign(self._prepared_xml(cdc=""))

    def test_duplicate_signature_is_rejected(self):
        root = etree.fromstring(self._prepared_xml())
        etree.SubElement(root, f"{{{self.XMLDSIG_NS}}}Signature")

        with self.assertRaisesRegex(ValidationError, "already contains Signature"):
            self._sign(etree.tostring(root))
