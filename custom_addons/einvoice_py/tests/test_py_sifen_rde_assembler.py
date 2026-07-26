from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests.common import BaseCase

from odoo.addons.einvoice_py.services.py_qr_generation_service import (
    PySifenQrBuilder,
)
from odoo.addons.einvoice_py.services.py_sifen_rde_assembler import (
    PySifenRdeAssembler,
)
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
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
            "errors": [] if self.valid else [{
                "message": "Element content is invalid.",
                "line": 7,
                "column": 3,
                "failing_element": "gCamFuFD",
                "path": "/rDE/gCamFuFD",
            }],
        }


class TestPySifenRdeAssembler(BaseCase):
    CDC = "01444444017001001001452822017012515873260988"
    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS
    XMLDSIG_NS = PyXmlSignatureService.XMLDSIG_NS

    def setUp(self):
        super().setUp()
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self.certificate = self._certificate()
        self.signature_result = PyXmlSignatureService().sign(
            prepared_xml_bytes=self._prepared_xml(),
            certificate_bytes=self.certificate.public_bytes(
                serialization.Encoding.PEM
            ),
            private_key_bytes=self.private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            cdc=self.CDC,
        )
        self.qr_result = PySifenQrBuilder().build(
            signed_xml_bytes=self.signature_result.signed_xml_bytes,
            cdc=self.CDC,
            digest_value=self.signature_result.digest_value,
            csc_id="0001",
            csc_secret="assembler-csc-fixture",
            environment="test",
        )

    def test_successful_assembly_and_official_order(self):
        xsd = _XsdValidationStub()

        result = self._assemble(xsd=xsd)

        self.assertTrue(result.xsd_valid)
        self.assertEqual(result.validation_errors, ())
        self.assertEqual(result.cdc, self.CDC)
        self.assertEqual(result.qr_url, self.qr_result.qr_string)
        self.assertEqual(xsd.calls, [result.final_xml_bytes])
        self.assertEqual(
            [etree.QName(child).localname for child in result.xml_document],
            ["dVerFor", "DE", "Signature", "gCamFuFD"],
        )

    def test_invalid_xsd_returns_structured_errors(self):
        result = self._assemble(xsd=_XsdValidationStub(valid=False))

        self.assertFalse(result.xsd_valid)
        self.assertEqual(len(result.validation_errors), 1)
        error = result.validation_errors[0]
        self.assertEqual(error.message, "Element content is invalid.")
        self.assertEqual(error.line, 7)
        self.assertEqual(error.element, "gCamFuFD")
        self.assertEqual(error.path, "/rDE/gCamFuFD")

    def test_missing_signature_is_rejected(self):
        root = etree.fromstring(self.signature_result.signed_xml_bytes)
        root.remove(root.find(f"{{{self.XMLDSIG_NS}}}Signature"))

        with self.assertRaisesRegex(ValidationError, "Signature"):
            self._assemble(signed_xml_bytes=etree.tostring(root))

    def test_missing_qr_is_rejected(self):
        group = etree.Element(f"{{{self.SIFEN_NS}}}gCamFuFD")

        with self.assertRaisesRegex(ValidationError, "dCarQR"):
            self._assemble(
                gcamfufd_xml_bytes=etree.tostring(group)
            )

    def test_namespace_and_signed_nodes_are_preserved(self):
        before = etree.fromstring(self.signature_result.signed_xml_bytes)
        result = self._assemble()
        after = result.xml_document

        self.assertEqual(after.nsmap, before.nsmap)
        self.assertEqual(
            etree.tostring(after.find(f"{{{self.SIFEN_NS}}}DE")),
            etree.tostring(before.find(f"{{{self.SIFEN_NS}}}DE")),
        )
        self.assertEqual(
            etree.tostring(
                after.find(f"{{{self.XMLDSIG_NS}}}Signature")
            ),
            etree.tostring(
                before.find(f"{{{self.XMLDSIG_NS}}}Signature")
            ),
        )

    def test_output_is_deterministic(self):
        first = self._assemble()
        second = self._assemble()

        self.assertEqual(first.final_xml_bytes, second.final_xml_bytes)

    def test_xmldsig_remains_valid_after_assembly(self):
        result = self._assemble()

        verification = PyXmlSignatureVerificationService().verify(
            signed_xml_bytes=result.final_xml_bytes,
            expected_cdc=self.CDC,
        )

        self.assertTrue(verification["valid"], verification["errors"])

    def test_invalid_signed_xml_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "Malformed"):
            self._assemble(signed_xml_bytes=b"<rDE>")

    def test_existing_qr_or_wrong_cdc_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "in order"):
            self._assemble(
                signed_xml_bytes=self._assemble().final_xml_bytes
            )
        with self.assertRaisesRegex(ValidationError, "CDC"):
            self._assemble(cdc="0" * 44)

    def _assemble(
        self,
        *,
        xsd=None,
        signed_xml_bytes=None,
        gcamfufd_xml_bytes=None,
        cdc=None,
    ):
        return PySifenRdeAssembler(
            xsd_validation_service=xsd or _XsdValidationStub()
        ).assemble(
            signed_xml_bytes=(
                signed_xml_bytes
                if signed_xml_bytes is not None
                else self.signature_result.signed_xml_bytes
            ),
            gcamfufd_xml_bytes=(
                gcamfufd_xml_bytes
                if gcamfufd_xml_bytes is not None
                else self.qr_result.gcamfufd_xml_bytes
            ),
            cdc=cdc or self.CDC,
            qr_url=self.qr_result.qr_string,
        )

    def _prepared_xml(self):
        root = etree.Element(
            f"{{{self.SIFEN_NS}}}rDE",
            nsmap={None: self.SIFEN_NS},
        )
        etree.SubElement(root, f"{{{self.SIFEN_NS}}}dVerFor").text = "150"
        de = etree.SubElement(
            root,
            f"{{{self.SIFEN_NS}}}DE",
            {"Id": self.CDC},
        )
        etree.SubElement(de, f"{{{self.SIFEN_NS}}}dDVId").text = self.CDC[-1]
        etree.SubElement(
            de,
            f"{{{self.SIFEN_NS}}}dFecFirma",
        ).text = "2026-06-18T12:34:56"
        etree.SubElement(de, f"{{{self.SIFEN_NS}}}dSisFact").text = "1"
        general = etree.SubElement(
            de,
            f"{{{self.SIFEN_NS}}}gDatGralOpe",
        )
        etree.SubElement(
            general,
            f"{{{self.SIFEN_NS}}}dFeEmiDE",
        ).text = "2026-06-18T12:00:00"
        receiver = etree.SubElement(
            general,
            f"{{{self.SIFEN_NS}}}gDatRec",
        )
        etree.SubElement(
            receiver,
            f"{{{self.SIFEN_NS}}}dRucRec",
        ).text = "1234567"
        detail = etree.SubElement(
            de,
            f"{{{self.SIFEN_NS}}}gDtipDE",
        )
        etree.SubElement(detail, f"{{{self.SIFEN_NS}}}gCamItem")
        totals = etree.SubElement(de, f"{{{self.SIFEN_NS}}}gTotSub")
        etree.SubElement(
            totals,
            f"{{{self.SIFEN_NS}}}dTotGralOpe",
        ).text = "100.00000000"
        etree.SubElement(
            totals,
            f"{{{self.SIFEN_NS}}}dTotIVA",
        ).text = "9.09000000"
        return etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
        )

    def _certificate(self):
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "rDE Fixture"),
        ])
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(self.private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2026, 6, 17))
            .not_valid_after(datetime(2026, 6, 18) + timedelta(days=30))
            .sign(self.private_key, hashes.SHA256())
        )
