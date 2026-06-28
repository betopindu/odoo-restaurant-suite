from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

from odoo.tests.common import BaseCase

from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)
from odoo.addons.einvoice_py.services.py_xml_signature_service import (
    PyXmlSignatureService,
)
from odoo.addons.einvoice_py.services.py_xml_signature_verification_service import (
    PyXmlSignatureVerificationService,
)


class TestPyXmlSignatureVerificationService(BaseCase):
    CDC = "01444444017001001001452822017012515873260988"
    SIGNING_TIME = "2026-06-18T12:34:56"
    XMLDSIG_NS = PyXmlSignatureService.XMLDSIG_NS

    def setUp(self):
        super().setUp()
        self.signing_service = PyXmlSignatureService()
        self.verification_service = PyXmlSignatureVerificationService()
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self.certificate = self._certificate(self.private_key)

    def _certificate(self, key):
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "XML Verification Fixture"),
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

    def _prepared_xml(self):
        namespace = PyUnsignedXmlBuilder.SIFEN_NS
        root = etree.Element(f"{{{namespace}}}rDE", nsmap={None: namespace})
        etree.SubElement(root, f"{{{namespace}}}dVerFor").text = "150"
        de = etree.SubElement(root, f"{{{namespace}}}DE", {"Id": self.CDC})
        etree.SubElement(de, f"{{{namespace}}}dDVId").text = self.CDC[-1]
        etree.SubElement(de, f"{{{namespace}}}dFecFirma").text = self.SIGNING_TIME
        etree.SubElement(de, f"{{{namespace}}}dSisFact").text = "1"
        etree.SubElement(de, f"{{{namespace}}}gOpeDE")
        etree.indent(root, space="  ")
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    def _signed_xml(self):
        return self.signing_service.sign(
            prepared_xml_bytes=self._prepared_xml(),
            certificate_bytes=self._certificate_bytes(),
            private_key_bytes=self._private_key_bytes(),
        )["signed_xml_bytes"]

    def _verify(self, xml_content=None, **overrides):
        values = {"signed_xml_bytes": xml_content or self._signed_xml()}
        values.update(overrides)
        return self.verification_service.verify(**values)

    def _root(self, xml_content=None):
        return etree.fromstring(xml_content or self._signed_xml())

    def _signature(self, root):
        return root.find(f"{{{self.XMLDSIG_NS}}}Signature")

    def test_valid_signed_xml_verifies(self):
        report = self._verify(expected_cdc=self.CDC)

        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["cdc"], self.CDC)
        self.assertEqual(report["reference_uri"], f"#{self.CDC}")
        self.assertFalse(report["warnings"])

    def test_tampered_signed_xml_fails(self):
        root = self._root()
        root.find(f".//{{{PyUnsignedXmlBuilder.SIFEN_NS}}}dSisFact").text = "2"

        report = self._verify(etree.tostring(root))

        self.assertFalse(report["valid"])
        self.assertIn(
            "Signed Paraguay XML cryptographic verification failed.",
            report["errors"],
        )

    def test_wrong_expected_cdc_fails(self):
        report = self._verify(expected_cdc="0" * 44)

        self.assertFalse(report["valid"])
        self.assertIn(
            "Signed Paraguay XML CDC does not match expected CDC.",
            report["errors"],
        )

    def test_wrong_expected_certificate_fingerprint_fails(self):
        report = self._verify(expected_certificate_fingerprint="0" * 64)

        self.assertFalse(report["valid"])
        self.assertIn(
            "Signed Paraguay XML certificate fingerprint does not match expected fingerprint.",
            report["errors"],
        )

    def test_missing_signature_fails(self):
        root = self._root()
        root.remove(self._signature(root))

        report = self._verify(etree.tostring(root))

        self.assertFalse(report["valid"])
        self.assertIn(
            "Signed Paraguay XML must contain exactly one Signature.",
            report["errors"],
        )

    def test_multiple_signature_fails(self):
        root = self._root()
        etree.SubElement(root, f"{{{self.XMLDSIG_NS}}}Signature")

        report = self._verify(etree.tostring(root))

        self.assertFalse(report["valid"])
        self.assertIn(
            "Signed Paraguay XML must contain exactly one Signature.",
            report["errors"],
        )

    def test_signature_before_de_fails(self):
        root = self._root()
        signature = self._signature(root)
        root.remove(signature)
        root.insert(1, signature)

        report = self._verify(etree.tostring(root))

        self.assertFalse(report["valid"])
        self.assertIn(
            "Signed Paraguay XML Signature must be after DE.",
            report["errors"],
        )

    def test_report_includes_digest_value_and_fingerprint(self):
        report = self._verify()

        self.assertTrue(report["valid"], report["errors"])
        self.assertTrue(report["digest_value"])
        self.assertEqual(len(report["certificate_fingerprint_sha256"]), 64)

    def test_algorithms_are_reported_and_checked(self):
        report = self._verify()

        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(
            report["canonicalization_method"],
            "http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
        )
        self.assertEqual(
            report["signature_method"],
            "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
        )
        self.assertEqual(
            report["digest_method"],
            "http://www.w3.org/2001/04/xmlenc#sha256",
        )
        self.assertEqual(
            report["transforms"],
            [
                "http://www.w3.org/2000/09/xmldsig#enveloped-signature",
                "http://www.w3.org/2001/10/xml-exc-c14n#",
            ],
        )

    def test_unsupported_algorithms_fail(self):
        root = self._root()
        signature_method = root.find(f".//{{{self.XMLDSIG_NS}}}SignatureMethod")
        signature_method.set("Algorithm", "urn:unsupported")

        report = self._verify(etree.tostring(root))

        self.assertFalse(report["valid"])
        self.assertIn(
            "Signed Paraguay XML uses unsupported algorithms.",
            report["errors"],
        )

    def test_reference_uri_mismatch_fails(self):
        root = self._root()
        reference = root.find(f".//{{{self.XMLDSIG_NS}}}Reference")
        reference.set("URI", "#0")

        report = self._verify(etree.tostring(root))

        self.assertFalse(report["valid"])
        self.assertIn(
            "Signed Paraguay XML Reference URI must match DE CDC.",
            report["errors"],
        )

    def test_malformed_xml_fails(self):
        report = self._verify(b"<rDE>")

        self.assertFalse(report["valid"])
        self.assertEqual(report["errors"], ["Malformed signed Paraguay XML."])

    def test_wrong_root_fails(self):
        root = self._root()
        root.tag = f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}wrongRoot"

        report = self._verify(etree.tostring(root))

        self.assertFalse(report["valid"])
        self.assertIn(
            "Signed Paraguay XML root must be rDE in the official SIFEN namespace.",
            report["errors"],
        )

    def test_missing_de_fails(self):
        root = self._root()
        de = root.find(f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}DE")
        root.remove(de)

        report = self._verify(etree.tostring(root))

        self.assertFalse(report["valid"])
        self.assertIn(
            "Signed Paraguay XML must contain exactly one DE.",
            report["errors"],
        )

    def test_multiple_de_fails(self):
        root = self._root()
        etree.SubElement(
            root,
            f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}DE",
            {"Id": self.CDC},
        )

        report = self._verify(etree.tostring(root))

        self.assertFalse(report["valid"])
        self.assertIn(
            "Signed Paraguay XML must contain exactly one DE.",
            report["errors"],
        )
