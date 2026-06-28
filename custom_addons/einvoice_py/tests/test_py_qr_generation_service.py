import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_qr_generation_service import (
    PyQrGenerationService,
)
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)


class TestPyQrGenerationService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"
    DIGEST_VALUE = "abc+/=digest-fixture"
    CSC_VALUE = "secret-csc-fixture"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "QR Generation Tenant",
            "code": "qr-generation",
            "company_id": cls.env.company.id,
        })
        cls.csc = cls.env["fiscal.py.csc"].create({
            "name": "QR CSC",
            "id_csc": "0001",
            "csc_value": cls.CSC_VALUE,
            "tenant_id": cls.tenant.id,
            "company_id": cls.env.company.id,
            "environment": "test",
        })
        cls.service = PyQrGenerationService()

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "QR Generation Document",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Test Customer",
            "amount_total": 100,
            "idempotency_key": self.id(),
            "py_cdc": self.CDC,
            "py_cdc_dv": self.CDC[-1],
            "country_identifier": self.CDC,
            "py_csc_id": self.csc.id,
        })

    def _signed_xml(
        self,
        *,
        cdc=None,
        include_signature=True,
        digest_value=None,
        digest_count=1,
        signature_count=1,
        receiver_ruc="1234567",
        receiver_dv="8",
        receiver_document=None,
    ):
        namespace = PyUnsignedXmlBuilder.SIFEN_NS
        root = etree.Element(f"{{{namespace}}}rDE", nsmap={None: namespace})
        etree.SubElement(root, f"{{{namespace}}}dVerFor").text = "150"
        de = etree.SubElement(root, f"{{{namespace}}}DE", {"Id": cdc or self.CDC})
        etree.SubElement(de, f"{{{namespace}}}dDVId").text = self.CDC[-1]
        etree.SubElement(de, f"{{{namespace}}}dFecFirma").text = "2026-06-18T12:34:56"
        etree.SubElement(de, f"{{{namespace}}}dSisFact").text = "1"
        general = etree.SubElement(de, f"{{{namespace}}}gDatGralOpe")
        etree.SubElement(general, f"{{{namespace}}}dFeEmiDE").text = "2026-06-18T12:00:00"
        receiver = etree.SubElement(general, f"{{{namespace}}}gDatRec")
        if receiver_ruc is not None:
            etree.SubElement(receiver, f"{{{namespace}}}dRucRec").text = receiver_ruc
        if receiver_dv is not None:
            etree.SubElement(receiver, f"{{{namespace}}}dDVRec").text = receiver_dv
        if receiver_document is not None:
            etree.SubElement(receiver, f"{{{namespace}}}dNumIDRec").text = receiver_document
        detail = etree.SubElement(de, f"{{{namespace}}}gDtipDE")
        etree.SubElement(detail, f"{{{namespace}}}gCamItem")
        totals = etree.SubElement(de, f"{{{namespace}}}gTotSub")
        etree.SubElement(totals, f"{{{namespace}}}dTotGralOpe").text = "100.00000000"
        etree.SubElement(totals, f"{{{namespace}}}dTotIVA").text = "9.09000000"
        if include_signature:
            ds_namespace = PyQrGenerationService.XMLDSIG_NS
            for _index in range(signature_count):
                signature = etree.SubElement(root, f"{{{ds_namespace}}}Signature")
                signed_info = etree.SubElement(signature, f"{{{ds_namespace}}}SignedInfo")
                reference = etree.SubElement(signed_info, f"{{{ds_namespace}}}Reference")
                for _digest_index in range(digest_count):
                    etree.SubElement(
                        reference,
                        f"{{{ds_namespace}}}DigestValue",
                    ).text = digest_value or self.DIGEST_VALUE
        etree.indent(root, space="  ")
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    def _generate(self, **overrides):
        values = {
            "document": self.document,
            "signed_xml_bytes": self._signed_xml(),
            "digest_value": self.DIGEST_VALUE,
            "cdc": self.CDC,
            "base_url": "https://example.test/qr",
        }
        values.update(overrides)
        return self.service.generate(**values)

    def _query_pairs(self, qr_string):
        return parse_qsl(urlsplit(qr_string).query, keep_blank_values=True)

    def test_valid_qr_payload_generated(self):
        result = self._generate()

        self.assertTrue(result["qr_string"].startswith("https://example.test/qr?"))
        self.assertEqual(len(result["qr_hash"]), 64)
        self.assertIn(("cHashQR", result["qr_hash"]), self._query_pairs(result["qr_string"]))
        self.assertNotIn(self.CSC_VALUE, result["qr_string"])

    def test_qr_payload_is_deterministic(self):
        first = self._generate()
        second = self._generate()

        self.assertEqual(first, second)

    def test_missing_input_digest_value_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "DigestValue is required"):
            self._generate(digest_value="")

    def test_missing_cdc_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "CDC is required"):
            self._generate(cdc="")

    def test_malformed_xml_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "Malformed signed Paraguay XML"):
            self._generate(signed_xml_bytes=b"<rDE>")

    def test_qr_content_matches_official_field_ordering(self):
        result = self._generate()

        self.assertEqual(
            [key for key, _value in self._query_pairs(result["qr_string"])],
            [
                "nVersion",
                "Id",
                "dFeEmiDE",
                "dRucRec",
                "dTotGralOpe",
                "dTotIVA",
                "cItems",
                "DigestValue",
                "IdCSC",
                "cHashQR",
            ],
        )

    def test_qr_content_uses_expected_values(self):
        result = self._generate()

        self.assertEqual(
            dict(self._query_pairs(result["qr_string"])),
            {
                "nVersion": "150",
                "Id": self.CDC,
                "dFeEmiDE": "2026-06-18T12:00:00",
                "dRucRec": "1234567",
                "dTotGralOpe": "100.00000000",
                "dTotIVA": "9.09000000",
                "cItems": "1",
                "DigestValue": self.DIGEST_VALUE,
                "IdCSC": "0001",
                "cHashQR": result["qr_hash"],
            },
        )

    def test_missing_csc_is_rejected(self):
        self.document.py_csc_id = False

        with self.assertRaisesRegex(ValidationError, "IdCSC and CSC are required"):
            self._generate()

    def test_project_locked_hash_vector(self):
        result = self._generate()
        fields = [
            ("nVersion", "150"),
            ("Id", self.CDC),
            ("dFeEmiDE", "2026-06-18T12:00:00"),
            ("dRucRec", "1234567"),
            ("dTotGralOpe", "100.00000000"),
            ("dTotIVA", "9.09000000"),
            ("cItems", "1"),
            ("DigestValue", self.DIGEST_VALUE),
            ("IdCSC", "0001"),
        ]
        expected_hash = hashlib.sha256(
            (urlencode(fields) + self.CSC_VALUE).encode("utf-8")
        ).hexdigest()

        self.assertEqual(result["qr_hash"], expected_hash)

    def test_digest_value_mismatch_is_rejected(self):
        signed_xml = self._signed_xml(digest_value="different-digest")

        with self.assertRaisesRegex(ValidationError, "DigestValue must match"):
            self._generate(signed_xml_bytes=signed_xml)

    def test_missing_signature_is_rejected(self):
        signed_xml = self._signed_xml(include_signature=False)

        with self.assertRaisesRegex(ValidationError, "exactly one XMLDSig Signature"):
            self._generate(signed_xml_bytes=signed_xml)

    def test_multiple_signature_is_rejected(self):
        signed_xml = self._signed_xml(signature_count=2)

        with self.assertRaisesRegex(ValidationError, "exactly one XMLDSig Signature"):
            self._generate(signed_xml_bytes=signed_xml)

    def test_missing_xml_digest_value_is_rejected(self):
        signed_xml = self._signed_xml(digest_count=0)

        with self.assertRaisesRegex(ValidationError, "exactly one XMLDSig DigestValue"):
            self._generate(signed_xml_bytes=signed_xml)

    def test_multiple_digest_value_is_rejected(self):
        signed_xml = self._signed_xml(digest_count=2)

        with self.assertRaisesRegex(ValidationError, "exactly one XMLDSig DigestValue"):
            self._generate(signed_xml_bytes=signed_xml)

    def test_receiver_ruc_uses_official_druc_field_without_dv_suffix(self):
        result = self._generate()

        self.assertIn(("dRucRec", "1234567"), self._query_pairs(result["qr_string"]))
        self.assertNotIn(("dRucRec", "1234567-8"), self._query_pairs(result["qr_string"]))

    def test_receiver_document_does_not_replace_missing_druc_field(self):
        signed_xml = self._signed_xml(
            receiver_ruc=None,
            receiver_dv=None,
            receiver_document="4444444",
        )

        with self.assertRaisesRegex(ValidationError, "receiver RUC is required"):
            self._generate(signed_xml_bytes=signed_xml)
