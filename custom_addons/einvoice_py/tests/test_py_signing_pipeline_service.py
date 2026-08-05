import base64
import hashlib
import json
from datetime import datetime, timedelta
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_signing_pipeline_service import (
    PySigningPipelineService,
)
from odoo.addons.einvoice_py.services.py_xml_signature_verification_service import (
    PyXmlSignatureVerificationService,
)


class TestPySigningPipelineService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"
    SIGNING_TIMESTAMP = datetime(2026, 6, 18, 12, 34, 56)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "Signing Pipeline Tenant",
            "code": "signing-pipeline",
            "company_id": cls.env.company.id,
        })
        cls.service = PySigningPipelineService(cls.env)

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "Signing Pipeline Document",
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
        })
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self.certificate = self._certificate(self.private_key)

    def _certificate(self, key):
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Signing Pipeline Fixture"),
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

    def _payload(self, *, cdc=None):
        cdc = cdc or self.CDC
        return {
            "version": "150",
            "cdc": cdc,
            "document": {
                "py_cdc": cdc,
                "py_cdc_dv": cdc[-1],
                "py_i_tide": "01",
                "py_document_number": "0000001",
                "issue_datetime": "2026-06-18T12:00:00",
                "py_emission_type": "1",
                "py_cod_seg": "123456789",
            },
            "issuer": {
                "ruc": "44444401",
                "ruc_dv": "7",
                "name": "Signing Pipeline Issuer",
                "taxpayer_type": "1",
                "timbrado_number": "12345678",
                "timbrado_valid_from": "2026-01-01",
                "establishment_code": "001",
                "point_of_issue_code": "001",
                "address": "Issuer address",
                "house_number": "123",
                "department_code": "1",
                "department_name": "CAPITAL",
                "district_code": "1",
                "district_name": "ASUNCION",
                "city_code": "1",
                "city_name": "ASUNCION",
                "phone": "021000000",
                "email": "issuer@example.com",
                "branch_name": "Main branch",
                "economic_activities": [
                    {"code": "62010", "description": "Software services"},
                ],
            },
            "receiver": {
                "nature_code": "1",
                "type_code": "1",
                "country_code": "PRY",
                "country_description": "Paraguay",
                "taxpayer_type": "1",
                "ruc_or_document": "1234567",
                "ruc_dv": "8",
                "name": "Test Customer",
                "address": "Receiver address",
                "house_number": "456",
                "department_code": "1",
                "department_name": "CAPITAL",
                "district_code": "1",
                "district_name": "ASUNCION",
                "city_code": "1",
                "city_name": "ASUNCION",
                "phone": "0981000000",
                "email": "customer@example.com",
                "customer_code": "CUST-001",
            },
            "operation": {
                "transaction_type_code": "2",
                "transaction_type_description": "Prestación de servicios",
                "tax_type_code": "1",
                "tax_type_description": "IVA",
                "currency": "PYG",
                "currency_description": "Guarani",
                "exchange_rate": 1,
            },
            "condition": {
                "sale_condition_code": "1",
                "sale_condition_description": "Contado",
                "payment_type_code": "1",
                "payment_type_description": "Efectivo",
                "payment_amount": 100,
                "payment_currency": "PYG",
                "payment_currency_description": "Guarani",
            },
            "items": [
                {
                    "code": "ITEM-001",
                    "description": "Signing pipeline item",
                    "unit_measure_code": "77",
                    "unit_measure_description": "UNI",
                    "quantity": 1,
                    "price_unit": 100,
                    "total": 100,
                    "discount": 0,
                    "discount_percent": 0,
                    "tax_affectation": "1",
                    "tax_affectation_description": "Gravado IVA",
                    "tax_proportion": 100,
                    "tax_rate": 10,
                    "tax_base": 90.91,
                    "tax_amount": 9.09,
                    "exempt_base": 0,
                },
            ],
            "totals": {
                "subtotal_exempt": 0,
                "subtotal_5": 0,
                "subtotal_10": 100,
                "total_operation": 100,
                "total_discount": 0,
                "total_general": 100,
                "total_vat_5": 0,
                "total_vat_10": 9.09,
                "total_vat": 9.09,
            },
        }

    def _run_pipeline(self, **overrides):
        values = {
            "document": self.document,
            "payload": self._payload(),
            "certificate_bytes": self._certificate_bytes(),
            "private_key_bytes": self._private_key_bytes(),
            "signing_timestamp": self.SIGNING_TIMESTAMP,
        }
        values.update(overrides)
        return self.service.sign(**values)

    def _signed_attachment(self):
        return self.env["fiscal.attachment"].search([
            ("document_id", "=", self.document.id),
            ("attachment_type", "=", "paraguay_xml_signed"),
        ])

    def _create_unsigned_attachment(self):
        content = b"<unsigned-fixture/>"
        filename = f"{self.document.uuid}-paraguay-unsigned.xml"
        ir_attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(content),
            "mimetype": "application/xml",
            "res_model": "fiscal.document",
            "res_id": self.document.id,
        })
        return self.env["fiscal.attachment"].sudo().create({
            "name": filename,
            "document_id": self.document.id,
            "attachment_type": "paraguay_xml_unsigned",
            "mimetype": "application/xml",
            "filename": filename,
            "ir_attachment_id": ir_attachment.id,
            "sha256": hashlib.sha256(content).hexdigest(),
            "is_sensitive": True,
        })

    def test_successful_end_to_end_signing(self):
        report = self._run_pipeline()
        attachment = self._signed_attachment()
        metadata = json.loads(attachment.metadata_json)

        self.assertEqual(report["cdc"], self.CDC)
        self.assertTrue(report["digest_value"])
        self.assertEqual(len(report["certificate_fingerprint_sha256"]), 64)
        self.assertEqual(report["signed_attachment_id"], attachment.id)
        self.assertTrue(report["verification_result"]["valid"])
        self.assertEqual(len(attachment), 1)
        self.assertEqual(metadata["cdc"], self.CDC)
        self.assertEqual(metadata["digest_value"], report["digest_value"])
        self.assertEqual(
            metadata["certificate_fingerprint_sha256"],
            report["certificate_fingerprint_sha256"],
        )
        self.assertEqual(metadata["signing_time"], "2026-06-18T09:34:56")

    def test_preparation_failure_aborts_pipeline(self):
        with self.assertRaises(ValidationError):
            self._run_pipeline(payload=self._payload(cdc="0" * 44))

        self.assertFalse(self._signed_attachment())

    def test_signing_failure_aborts_pipeline(self):
        with patch(
            "odoo.addons.einvoice_py.services.py_xml_signature_service."
            "PyXmlSignatureService.sign",
            side_effect=ValidationError("signing failed"),
        ):
            with self.assertRaisesRegex(ValidationError, "signing failed"):
                self._run_pipeline()

        self.assertFalse(self._signed_attachment())

    def test_verification_failure_aborts_pipeline(self):
        with patch(
            "odoo.addons.einvoice_py.services.py_xml_signature_verification_service."
            "PyXmlSignatureVerificationService.verify",
            return_value={"valid": False, "errors": ["verification failed"]},
        ):
            with self.assertRaisesRegex(ValidationError, "verification failed"):
                self._run_pipeline()

        self.assertFalse(self._signed_attachment())

    def test_attachment_persistence_failure_aborts_pipeline(self):
        with patch(
            "odoo.addons.einvoice_py.services.py_signed_xml_attachment_service."
            "PySignedXmlAttachmentService.persist",
            side_effect=ValidationError("persistence failed"),
        ):
            with self.assertRaisesRegex(ValidationError, "persistence failed"):
                self._run_pipeline()

        self.assertFalse(self._signed_attachment())

    def test_signed_attachment_exists_after_success(self):
        self._run_pipeline()

        self.assertEqual(len(self._signed_attachment()), 1)

    def test_changed_signing_time_never_returns_stale_signed_xml(self):
        first_report = self._run_pipeline()
        first_attachment = self.env["fiscal.attachment"].browse(
            first_report["signed_attachment_id"]
        )

        second_report = self._run_pipeline(
            signing_timestamp=datetime(2026, 6, 18, 12, 35, 56)
        )
        second_attachment = self.env["fiscal.attachment"].browse(
            second_report["signed_attachment_id"]
        )
        verification = PyXmlSignatureVerificationService().verify(
            signed_xml_bytes=base64.b64decode(
                second_attachment.ir_attachment_id.datas
            ),
            expected_cdc=self.CDC,
        )

        self.assertNotEqual(first_attachment, second_attachment)
        self.assertEqual(
            verification["digest_value"], second_report["digest_value"]
        )
        self.assertEqual(
            json.loads(first_attachment.metadata_json)["artifact_status"],
            "superseded",
        )
        self.assertEqual(
            json.loads(second_attachment.metadata_json)["artifact_status"],
            "current",
        )

    def test_unsigned_attachment_remains_unchanged(self):
        unsigned_attachment = self._create_unsigned_attachment()
        original_hash = unsigned_attachment.sha256
        original_ir_attachment = unsigned_attachment.ir_attachment_id

        self._run_pipeline()

        unsigned_attachment.invalidate_recordset()
        self.assertEqual(unsigned_attachment.sha256, original_hash)
        self.assertEqual(unsigned_attachment.ir_attachment_id, original_ir_attachment)
        self.assertEqual(len(self._signed_attachment()), 1)

    def test_no_duplicate_signed_attachment_on_retry(self):
        first = self._run_pipeline()
        second = self._run_pipeline()

        self.assertEqual(first["signed_attachment_id"], second["signed_attachment_id"])
        self.assertEqual(len(self._signed_attachment()), 1)
