import base64
import hashlib
import json

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_kude_service import PyKudeService
from odoo.addons.einvoice_py.services.py_qr_payload_attachment_service import (
    PyQrPayloadAttachmentService,
)


class TestPyKudeService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"
    QR_HASH = "a" * 64
    QR_URL = (
        "https://ekuatia.set.gov.py/consultas-test/qr?nVersion=150&Id="
        + CDC
        + "&cHashQR="
        + QR_HASH
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "KuDE Tenant",
            "code": "kude-tenant",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "KuDE Invoice",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Test Receiver",
            "amount_total": 110000,
            "idempotency_key": self.id(),
            "py_cdc": self.CDC,
            "country_identifier": self.CDC,
        })
        self.qr_service = PyQrPayloadAttachmentService(self.env)
        self.service = PyKudeService(
            self.env,
            qr_attachment_service=self.qr_service,
        )

    def _payload(self, **overrides):
        payload = {
            "version": "150",
            "cdc": self.CDC,
            "document": {
                "document_type": "invoice",
                "py_full_number": "001-001-0000001",
                "issue_datetime": "2026-08-06T14:00:00",
            },
            "operation": {
                "transaction_type_description": "Prestacion de servicios",
                "currency": "PYG",
                "currency_description": "Guarani",
            },
            "issuer": {
                "name": "EMISOR DE PRUEBA",
                "full_ruc": "4444444-0",
                "address": "DIRECCION EMISOR",
                "city_name": "ASUNCION",
                "timbrado_number": "4444444",
                "timbrado_valid_from": "2026-01-01",
                "timbrado_valid_to": "2026-12-31",
                "economic_activities": [
                    {"code": "62090", "description": "Servicios informaticos"},
                ],
            },
            "receiver": {
                "nature_code": "1",
                "ruc_or_document": "80000000",
                "ruc_dv": "0",
                "name": "RECEPTOR DE PRUEBA",
                "address": "DIRECCION RECEPTOR",
                "phone": "021000000",
                "email": "receiver@example.test",
            },
            "condition": {
                "sale_condition_description": "Contado",
            },
            "items": [
                {
                    "code": "ITEM-1",
                    "description": "Servicio de prueba",
                    "unit_measure_description": "UNI",
                    "quantity": 1,
                    "price_unit": 110000,
                    "discount": 0,
                    "total": 110000,
                    "tax_affectation": "1",
                    "tax_rate": 10,
                },
            ],
            "totals": {
                "subtotal_exempt": 0,
                "subtotal_5": 0,
                "subtotal_10": 110000,
                "total_operation": 110000,
                "total_general": 110000,
                "total_vat_5": 0,
                "total_vat_10": 10000,
                "total_vat": 10000,
            },
        }
        payload.update(overrides)
        return payload

    def _persist_payload(self, payload=None):
        return self.env["fiscal.attachment"].sudo().create_json_payload_attachment(
            self.document,
            "paraguay_payload_json",
            f"{self.document.uuid}-payload.json",
            payload or self._payload(),
        )

    def _persist_qr(self, qr_url=None, qr_hash=None):
        return self.qr_service.persist(
            document=self.document,
            qr_payload=qr_url or self.QR_URL,
            qr_hash=qr_hash or self.QR_HASH,
        )

    def _prepare(self):
        payload = self._persist_payload()
        qr = self._persist_qr()
        return payload, qr

    def test_generates_deterministic_versioned_pdf_from_persisted_artifacts(self):
        payload, qr = self._prepare()

        first = self.service.generate(document=self.document)
        second = PyKudeService(self.env).generate(document=self.document)

        self.assertTrue(first.pdf_bytes.startswith(b"%PDF-"))
        self.assertEqual(first.pdf_bytes, second.pdf_bytes)
        self.assertEqual(first.attachment_id, second.attachment_id)
        self.assertEqual(first.payload_attachment_id, payload.id)
        self.assertEqual(first.qr_attachment_id, qr.id)
        self.assertEqual(first.sha256, hashlib.sha256(first.pdf_bytes).hexdigest())
        self.assertEqual(first.page_count, 1)
        attachment = self.env["fiscal.attachment"].browse(first.attachment_id)
        self.assertEqual(attachment.attachment_type, "paraguay_kude_pdf")
        self.assertEqual(attachment.mimetype, "application/pdf")
        self.assertTrue(attachment.is_sensitive)

    def test_qr_payload_is_reused_exactly_and_never_recalculated(self):
        self._persist_payload()
        qr = self._persist_qr()

        result = self.service.generate(document=self.document)
        metadata = json.loads(
            self.env["fiscal.attachment"].browse(result.attachment_id).metadata_json
        )

        self.assertEqual(result.qr_attachment_id, qr.id)
        self.assertEqual(
            metadata["qr_payload_sha256"],
            hashlib.sha256(self.QR_URL.encode()).hexdigest(),
        )
        self.assertNotIn("csc", json.dumps(metadata).lower())

    def test_changed_payload_creates_new_current_pdf_and_preserves_history(self):
        self._prepare()
        first = self.service.generate(document=self.document)
        changed = self._payload()
        changed["receiver"]["name"] = "RECEPTOR CORREGIDO"
        self._persist_payload(changed)

        second = self.service.generate(document=self.document)

        self.assertNotEqual(first.attachment_id, second.attachment_id)
        first_attachment = self.env["fiscal.attachment"].browse(first.attachment_id)
        second_attachment = self.env["fiscal.attachment"].browse(second.attachment_id)
        first_metadata = json.loads(first_attachment.metadata_json)
        self.assertEqual(first_metadata["artifact_status"], "superseded")
        self.assertEqual(
            first_metadata["superseded_by_attachment_id"],
            second.attachment_id,
        )
        self.assertEqual(json.loads(second_attachment.metadata_json)["artifact_status"], "current")
        self.assertTrue(first_attachment.ir_attachment_id.exists())
        self.assertEqual(self.service.current(document=self.document), second_attachment)

    def test_changed_qr_versions_qr_and_pdf_without_mutating_payload(self):
        payload, first_qr = self._prepare()
        first = self.service.generate(document=self.document)
        changed_hash = "b" * 64
        changed_url = self.QR_URL.replace(self.QR_HASH, changed_hash)
        second_qr = self._persist_qr(changed_url, changed_hash)

        second = self.service.generate(document=self.document)

        self.assertNotEqual(first_qr, second_qr)
        self.assertNotEqual(first.attachment_id, second.attachment_id)
        self.assertEqual(second.payload_attachment_id, payload.id)
        self.assertEqual(json.loads(first_qr.metadata_json)["artifact_status"], "superseded")
        self.assertEqual(self.qr_service.current(document=self.document), second_qr)

    def test_multiple_pages_are_numbered_deterministically(self):
        payload = self._payload()
        payload["items"] = payload["items"] * 19
        self._persist_payload(payload)
        self._persist_qr()

        result = self.service.generate(document=self.document)

        self.assertEqual(result.page_count, 2)
        self.assertEqual(result.pdf_bytes, self.service.generate(document=self.document).pdf_bytes)

    def test_two_service_instances_are_idempotent_under_document_lock(self):
        self._prepare()

        first = PyKudeService(self.env).generate(document=self.document)
        second = PyKudeService(self.env).generate(document=self.document)
        attachments = self.env["fiscal.attachment"].search([
            ("document_id", "=", self.document.id),
            ("attachment_type", "=", "paraguay_kude_pdf"),
        ])

        self.assertEqual(first.attachment_id, second.attachment_id)
        self.assertEqual(len(attachments), 1)

    def test_missing_or_invalid_persisted_inputs_are_rejected_safely(self):
        with self.assertRaisesRegex(ValidationError, "payload is missing"):
            self.service.generate(document=self.document)

        self._persist_payload()
        with self.assertRaisesRegex(ValidationError, "QR payload is missing"):
            self.service.generate(document=self.document)

        bad_hash = "b" * 64
        with self.assertRaisesRegex(ValidationError, "does not match"):
            self._persist_qr(self.QR_URL, bad_hash)

    def test_payload_cdc_mismatch_and_unsupported_document_are_rejected(self):
        payload = self._payload(cdc="0" * 44)
        self._persist_payload(payload)
        self._persist_qr()
        with self.assertRaisesRegex(ValidationError, "CDC is invalid"):
            self.service.generate(document=self.document)

        self.document.document_type = "credit_note"
        with self.assertRaisesRegex(ValidationError, "invoices only"):
            self.service.generate(document=self.document)

    def test_result_repr_does_not_include_pdf_bytes(self):
        self._prepare()

        result = self.service.generate(document=self.document)

        self.assertNotIn("%PDF", repr(result))
        self.assertNotIn(self.QR_URL, repr(result))
