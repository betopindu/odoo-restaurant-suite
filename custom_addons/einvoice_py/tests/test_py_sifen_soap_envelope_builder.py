from datetime import datetime, timedelta
from dataclasses import FrozenInstanceError

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests.common import BaseCase

from odoo.addons.einvoice_py.services.py_sifen_soap_envelope_builder import (
    PySifenSoapEnvelopeBuilder,
)
from odoo.addons.einvoice_py.services.py_xml_signature_service import (
    PyXmlSignatureService,
)
from odoo.addons.einvoice_py.services.py_xml_signature_verification_service import (
    PyXmlSignatureVerificationService,
)


class _XsdValidationStub:
    def __init__(self, valid=True):
        self.valid = valid
        self.calls = []

    def validate_final_signed_xml(self, xml_content):
        self.calls.append(xml_content)
        return {
            "valid": self.valid,
            "errors": [] if self.valid else [{"message": "Invalid fixture."}],
        }


class TestPySifenSoapEnvelopeBuilder(BaseCase):
    CDC = "01444444017001001001452822017012515873260988"
    SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
    SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
    XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"

    def test_successful_generation_has_official_structure_and_metadata(self):
        validator = _XsdValidationStub()

        result = self._build(validator=validator)

        self.assertEqual(result.service_name, "siRecepDE")
        self.assertIsNone(result.soap_action)
        self.assertEqual(result.cdc, self.CDC)
        self.assertEqual(result.submission_id, "7")
        self.assertEqual(validator.calls, [self._rde()])
        self.assertEqual(
            result.xml_document.tag,
            f"{{{self.SOAP_NS}}}Envelope",
        )
        request_node = result.xml_document.find(
            f"{{{self.SOAP_NS}}}Body/"
            f"{{{self.SIFEN_NS}}}rEnviDe"
        )
        self.assertEqual(
            [etree.QName(child).localname for child in request_node],
            ["dId", "xDE"],
        )
        self.assertEqual(
            request_node.findtext(f"{{{self.SIFEN_NS}}}dId"),
            "7",
        )
        self.assertIsNotNone(
            request_node.find(
                f"{{{self.SIFEN_NS}}}xDE/"
                f"{{{self.SIFEN_NS}}}rDE"
            )
        )

    def test_rde_signed_content_namespaces_and_qr_are_unchanged(self):
        original = etree.fromstring(self._rde())
        result = self._build()
        embedded = result.xml_document.find(
            f"{{{self.SOAP_NS}}}Body/"
            f"{{{self.SIFEN_NS}}}rEnviDe/"
            f"{{{self.SIFEN_NS}}}xDE/"
            f"{{{self.SIFEN_NS}}}rDE"
        )

        self.assertEqual(
            etree.tostring(
                embedded.find(f"{{{self.SIFEN_NS}}}DE"),
                method="c14n",
            ),
            etree.tostring(
                original.find(f"{{{self.SIFEN_NS}}}DE"),
                method="c14n",
            ),
        )
        self.assertEqual(
            etree.tostring(
                embedded.find(f"{{{self.XMLDSIG_NS}}}Signature"),
                method="c14n",
            ),
            etree.tostring(
                original.find(f"{{{self.XMLDSIG_NS}}}Signature"),
                method="c14n",
            ),
        )
        self.assertEqual(
            embedded.findtext(
                f"{{{self.SIFEN_NS}}}gCamFuFD/"
                f"{{{self.SIFEN_NS}}}dCarQR"
            ),
            "https://example.test/qr?a=1&b=2",
        )

    def test_output_is_deterministic_and_not_pretty_printed(self):
        first = self._build()
        second = self._build()

        self.assertEqual(first.soap_xml_bytes, second.soap_xml_bytes)
        self.assertNotIn(b"\n  <", first.soap_xml_bytes)

    def test_explicit_soap_action_is_returned_as_metadata(self):
        result = self._build(soap_action="urn:fixture-action")

        self.assertEqual(result.soap_action, "urn:fixture-action")
        with self.assertRaises(FrozenInstanceError):
            result.cdc = "changed"

    def test_soap_wrapping_does_not_change_xmldsig(self):
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        certificate = self._certificate(private_key)
        signature = PyXmlSignatureService().sign(
            prepared_xml_bytes=self._prepared_rde(),
            certificate_bytes=certificate.public_bytes(
                serialization.Encoding.PEM
            ),
            private_key_bytes=private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            cdc=self.CDC,
        )
        signed_root = etree.fromstring(signature.signed_xml_bytes)
        qr_group = etree.SubElement(
            signed_root,
            f"{{{self.SIFEN_NS}}}gCamFuFD",
        )
        etree.SubElement(
            qr_group,
            f"{{{self.SIFEN_NS}}}dCarQR",
        ).text = "https://example.test/qr?a=1&b=2"

        result = self._build(rde=etree.tostring(signed_root))
        embedded = result.xml_document.find(
            f"{{{self.SOAP_NS}}}Body/"
            f"{{{self.SIFEN_NS}}}rEnviDe/"
            f"{{{self.SIFEN_NS}}}xDE/"
            f"{{{self.SIFEN_NS}}}rDE"
        )
        verification = PyXmlSignatureVerificationService().verify(
            signed_xml_bytes=etree.tostring(embedded),
            expected_cdc=self.CDC,
        )

        self.assertTrue(verification["valid"], verification["errors"])

    def test_xsd_invalid_rde_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "XSD validation"):
            self._build(validator=_XsdValidationStub(valid=False))

    def test_malformed_wrong_root_and_missing_signature_are_rejected(self):
        unsigned = etree.fromstring(self._rde())
        unsigned.remove(
            unsigned.find(f"{{{self.XMLDSIG_NS}}}Signature")
        )
        invalid_inputs = [
            (b"<rDE>", "Malformed"),
            (
                f'<notRDE xmlns="{self.SIFEN_NS}"/>'.encode(),
                "final Paraguay rDE",
            ),
            (
                etree.tostring(unsigned),
                "Signature",
            ),
        ]
        for xml_content, message in invalid_inputs:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValidationError, message):
                    self._build(rde=xml_content)

    def test_missing_qr_and_invalid_submission_id_are_rejected(self):
        without_qr = self._rde().replace(
            b"<gCamFuFD><dCarQR>https://example.test/qr?a=1&amp;b=2"
            b"</dCarQR></gCamFuFD>",
            b"",
        )
        with self.assertRaisesRegex(ValidationError, "dCarQR"):
            self._build(rde=without_qr)

        for submission_id in ("", "abc", "1" * 16):
            with self.subTest(submission_id=submission_id):
                with self.assertRaisesRegex(ValidationError, "1 to 15 digits"):
                    self._build(submission_id=submission_id)

    def _build(
        self,
        *,
        validator=None,
        rde=None,
        submission_id="7",
        soap_action=None,
    ):
        return PySifenSoapEnvelopeBuilder(
            xsd_validation_service=validator or _XsdValidationStub()
        ).build(
            validated_rde_bytes=rde if rde is not None else self._rde(),
            submission_id=submission_id,
            soap_action=soap_action,
        )

    def _rde(self):
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<rDE xmlns="{self.SIFEN_NS}">
<dVerFor>150</dVerFor>
<DE Id="{self.CDC}"><gDatGralOpe><dFeEmiDE>2026-07-26T12:00:00</dFeEmiDE></gDatGralOpe></DE>
<ds:Signature xmlns:ds="{self.XMLDSIG_NS}"><ds:SignedInfo><ds:Reference URI="#{self.CDC}"><ds:DigestValue>Zml4dHVyZQ==</ds:DigestValue></ds:Reference></ds:SignedInfo><ds:SignatureValue>c2lnbmF0dXJl</ds:SignatureValue></ds:Signature>
<gCamFuFD><dCarQR>https://example.test/qr?a=1&amp;b=2</dCarQR></gCamFuFD>
</rDE>""".encode("utf-8")

    def _prepared_rde(self):
        root = etree.Element(
            f"{{{self.SIFEN_NS}}}rDE",
            nsmap={None: self.SIFEN_NS},
        )
        etree.SubElement(
            root,
            f"{{{self.SIFEN_NS}}}dVerFor",
        ).text = "150"
        de = etree.SubElement(
            root,
            f"{{{self.SIFEN_NS}}}DE",
            {"Id": self.CDC},
        )
        etree.SubElement(
            de,
            f"{{{self.SIFEN_NS}}}dDVId",
        ).text = self.CDC[-1]
        return etree.tostring(root)

    def _certificate(self, private_key):
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "SOAP Fixture"),
        ])
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2026, 7, 25))
            .not_valid_after(datetime(2026, 7, 26) + timedelta(days=30))
            .sign(private_key, hashes.SHA256())
        )
