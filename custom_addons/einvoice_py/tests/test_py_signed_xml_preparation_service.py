from datetime import datetime, timezone

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_signed_xml_preparation_service import (
    PySignedXmlPreparationService,
)
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)


class TestPySignedXmlPreparationService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"
    SIGNING_TIMESTAMP = datetime(2026, 6, 18, 12, 34, 56, 987654)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tenant = cls.env["fiscal.tenant"].create({
            "name": "Signed XML Preparation Tenant",
            "code": "signed-xml-preparation",
            "company_id": cls.env.company.id,
        })
        cls.document = cls.env["fiscal.document"].create({
            "name": "Signed XML Preparation Document",
            "tenant_id": tenant.id,
            "company_id": cls.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Test Customer",
            "amount_total": 100,
            "idempotency_key": "signed-xml-preparation-document",
            "py_cdc": cls.CDC,
            "py_cdc_dv": cls.CDC[-1],
            "country_identifier": cls.CDC,
        })
        cls.service = PySignedXmlPreparationService()

    def _unsigned_xml(
        self,
        *,
        cdc=None,
        include_de=True,
        include_dvid=True,
        include_dsisfact=True,
    ):
        namespace = PyUnsignedXmlBuilder.SIFEN_NS
        root = etree.Element(f"{{{namespace}}}rDE", nsmap={None: namespace})
        etree.SubElement(root, f"{{{namespace}}}dVerFor").text = "150"
        if include_de:
            attributes = {}
            if cdc is not False:
                attributes["Id"] = cdc or self.CDC
            de = etree.SubElement(root, f"{{{namespace}}}DE", attributes)
            if include_dvid:
                etree.SubElement(de, f"{{{namespace}}}dDVId").text = self.CDC[-1]
            if include_dsisfact:
                etree.SubElement(de, f"{{{namespace}}}dSisFact").text = "1"
            etree.SubElement(de, f"{{{namespace}}}gOpeDE")
        etree.indent(root, space="  ")
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    def _prepare(self, xml_content=None, timestamp=None, document=None):
        return self.service.prepare(
            document or self.document,
            xml_content or self._unsigned_xml(),
            timestamp or self.SIGNING_TIMESTAMP,
        )

    def _de_children(self, prepared_xml):
        root = etree.fromstring(prepared_xml)
        de = root.find(f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}DE")
        return [etree.QName(child).localname for child in de]

    def test_valid_insertion_is_immediately_after_dvid(self):
        result = self._prepare()

        self.assertEqual(
            self._de_children(result["prepared_xml_bytes"])[:3],
            ["dDVId", "dFecFirma", "dSisFact"],
        )
        root = etree.fromstring(result["prepared_xml_bytes"])
        signing_time = root.find(
            f".//{{{PyUnsignedXmlBuilder.SIFEN_NS}}}dFecFirma"
        )
        self.assertEqual(signing_time.text, "2026-06-18T09:33:56")

    def test_prepared_output_contains_no_signature(self):
        result = self._prepare()
        root = etree.fromstring(result["prepared_xml_bytes"])

        self.assertFalse(
            root.xpath(".//*[local-name()='Signature']")
        )

    def test_prepared_output_contains_no_qr_stage_content(self):
        result = self._prepare()
        root = etree.fromstring(result["prepared_xml_bytes"])

        self.assertFalse(
            root.xpath(
                ".//*[local-name()='gCamFuFD' or local-name()='dCarQR']"
            )
        )

    def test_existing_order_after_dsisfact_is_preserved(self):
        result = self._prepare()

        self.assertEqual(
            self._de_children(result["prepared_xml_bytes"]),
            ["dDVId", "dFecFirma", "dSisFact", "gOpeDE"],
        )

    def test_duplicate_dfecfirma_is_rejected(self):
        root = etree.fromstring(self._unsigned_xml())
        de = root.find(f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}DE")
        etree.SubElement(
            de,
            f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}dFecFirma",
        ).text = "2026-06-18T12:34:56"

        with self.assertRaisesRegex(ValidationError, "already contains dFecFirma"):
            self._prepare(etree.tostring(root))

    def test_cdc_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "DE Id must match"):
            self._prepare(self._unsigned_xml(cdc="0" * 44))

    def test_document_cdc_consistency_is_required(self):
        inconsistent = self.document.copy({
            "name": "Inconsistent CDC Document",
            "idempotency_key": "inconsistent-cdc-document",
            "py_cdc": self.CDC,
            "py_cdc_dv": self.CDC[-1],
            "country_identifier": "0" * 44,
        })

        with self.assertRaisesRegex(ValidationError, "country identifier must match"):
            self._prepare(document=inconsistent)

    def test_document_cdc_check_digit_consistency_is_required(self):
        inconsistent = self.document.copy({
            "name": "Inconsistent CDC Check Digit Document",
            "idempotency_key": "inconsistent-cdc-check-digit-document",
            "py_cdc": self.CDC,
            "py_cdc_dv": "0",
            "country_identifier": self.CDC,
        })

        with self.assertRaisesRegex(ValidationError, "check digit is inconsistent"):
            self._prepare(document=inconsistent)

    def test_missing_de_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "exactly one DE"):
            self._prepare(self._unsigned_xml(include_de=False))

    def test_wrong_root_is_rejected(self):
        namespace = PyUnsignedXmlBuilder.SIFEN_NS
        root = etree.Element(f"{{{namespace}}}wrongRoot", nsmap={None: namespace})
        etree.SubElement(root, f"{{{namespace}}}DE", {"Id": self.CDC})

        with self.assertRaisesRegex(ValidationError, "root must be rDE"):
            self._prepare(etree.tostring(root))

    def test_multiple_de_is_rejected(self):
        root = etree.fromstring(self._unsigned_xml())
        etree.SubElement(
            root,
            f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}DE",
            {"Id": self.CDC},
        )

        with self.assertRaisesRegex(ValidationError, "exactly one DE"):
            self._prepare(etree.tostring(root))

    def test_missing_de_id_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "missing Id"):
            self._prepare(self._unsigned_xml(cdc=False))

    def test_missing_dvid_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "exactly one dDVId"):
            self._prepare(self._unsigned_xml(include_dvid=False))

    def test_missing_dsisfact_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "exactly one dSisFact"):
            self._prepare(self._unsigned_xml(include_dsisfact=False))

    def test_dvid_mismatch_is_rejected(self):
        root = etree.fromstring(self._unsigned_xml())
        check_digit = root.find(
            f".//{{{PyUnsignedXmlBuilder.SIFEN_NS}}}dDVId"
        )
        check_digit.text = "0"

        with self.assertRaisesRegex(ValidationError, "dDVId must match"):
            self._prepare(etree.tostring(root))

    def test_malformed_xml_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "Malformed Paraguay unsigned XML"):
            self._prepare(b"<rDE>")

    def test_output_is_deterministic(self):
        first = self._prepare()
        second = self._prepare()

        self.assertEqual(
            first["prepared_xml_bytes"],
            second["prepared_xml_bytes"],
        )
        self.assertEqual(first["cdc"], self.CDC)
        self.assertEqual(first["signing_time"], "2026-06-18T09:33:56")

    def test_timezone_aware_timestamp_is_converted_to_paraguay(self):
        result = self._prepare(
            timestamp=datetime(
                2026,
                6,
                18,
                13,
                34,
                56,
                tzinfo=timezone.utc,
            )
        )

        self.assertEqual(result["signing_time"], "2026-06-18T10:33:56")

    def test_signature_present_is_rejected(self):
        root = etree.fromstring(self._unsigned_xml())
        etree.SubElement(
            root,
            "{http://www.w3.org/2000/09/xmldsig#}Signature",
        )

        with self.assertRaisesRegex(ValidationError, "signing or QR-stage content"):
            self._prepare(etree.tostring(root))

    def test_gcamfufd_present_is_rejected(self):
        root = etree.fromstring(self._unsigned_xml())
        etree.SubElement(
            root,
            f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}gCamFuFD",
        )

        with self.assertRaisesRegex(ValidationError, "signing or QR-stage content"):
            self._prepare(etree.tostring(root))

    def test_dcarqr_present_is_rejected(self):
        root = etree.fromstring(self._unsigned_xml())
        etree.SubElement(
            root,
            f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}dCarQR",
        )

        with self.assertRaisesRegex(ValidationError, "signing or QR-stage content"):
            self._prepare(etree.tostring(root))
