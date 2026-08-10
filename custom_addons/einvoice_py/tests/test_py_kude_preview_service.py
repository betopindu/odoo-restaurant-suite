import hashlib
import io

from PyPDF2 import PdfFileReader

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.controllers.fiscal_document_preview import (
    PyFiscalDocumentPreviewController,
)
from odoo.addons.einvoice_py.services.py_fiscal_document_delivery_service import (
    PyFiscalDocumentDeliveryService,
)
from odoo.addons.einvoice_py.services.py_kude_preview_service import (
    PyKudePreviewService,
)


class TestPyKudePreviewService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "Preview Tenant",
            "code": "preview-tenant",
            "company_id": cls.env.company.id,
        })
        cls.other_tenant = cls.env["fiscal.tenant"].create({
            "name": "Other Preview Tenant",
            "code": "other-preview-tenant",
            "company_id": cls.env.company.id,
        })
        cls.denied_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create({
            "name": "preview-denied",
            "login": "preview-denied",
            "email": "preview-denied@example.test",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
            "allowed_fiscal_tenant_ids": [(6, 0, [cls.other_tenant.id])],
        })

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "SIFEN PREVIEW TEST",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_sifen",
            "customer_name": "INNOMINADO",
            "amount_total": 165000,
            "idempotency_key": self.id(),
            "state": "ready",
            "py_cdc": self.CDC,
            "country_identifier": self.CDC,
            "py_full_number": "001-001-0000099",
        })
        self.payload_attachment = self.env["fiscal.attachment"].sudo(
        ).create_json_payload_attachment(
            self.document,
            "paraguay_payload_json",
            f"{self.document.uuid}-payload.json",
            self._payload(),
        )
        self.service = PyKudePreviewService(self.env)

    def _payload(self):
        return {
            "version": "150",
            "environment": "test",
            "cdc": self.CDC,
            "document": {
                "document_type": "invoice",
                "py_full_number": "001-001-0000099",
                "issue_datetime": "2026-08-10T10:00:00",
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
                "city_name": "SAN LORENZO",
                "timbrado_number": "4444444",
                "timbrado_valid_from": "2026-01-01",
                "timbrado_valid_to": "2026-12-31",
                "economic_activities": [
                    {"code": "62090", "description": "Servicios informaticos"},
                ],
            },
            "receiver": {
                "nature_code": "1",
                "document_number": "0",
                "name": "INNOMINADO",
            },
            "condition": {"sale_condition_description": "Contado"},
            "items": [
                {
                    "code": "ITEM-10",
                    "description": "Servicio gravado al diez por ciento",
                    "unit_measure_description": "UNI",
                    "quantity": 1,
                    "price_unit": 110000,
                    "discount": 0,
                    "total": 110000,
                    "tax_affectation": "1",
                    "tax_rate": 10,
                },
                {
                    "code": "ITEM-5",
                    "description": "Servicio gravado al cinco por ciento",
                    "unit_measure_description": "UNI",
                    "quantity": 1,
                    "price_unit": 55000,
                    "discount": 0,
                    "total": 55000,
                    "tax_affectation": "1",
                    "tax_rate": 5,
                },
            ],
            "totals": {
                "subtotal_exempt": 0,
                "subtotal_5": 55000,
                "subtotal_10": 110000,
                "total_operation": 165000,
                "total_general": 165000,
                "total_vat_5": 2619,
                "total_vat_10": 10000,
                "total_vat": 12619,
            },
        }

    def _text(self, pdf_bytes):
        reader = PdfFileReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extractText() for page in reader.pages)

    def test_preacceptance_preview_is_deterministic_and_non_authoritative(self):
        before = self.env["fiscal.attachment"].search_count([
            ("document_id", "=", self.document.id),
        ])
        first = self.service.render(document=self.document)
        second = PyKudePreviewService(self.env).render(document=self.document)
        text = self._text(first.pdf_bytes)

        self.assertTrue(first.pdf_bytes.startswith(b"%PDF-"))
        self.assertEqual(first.pdf_bytes, second.pdf_bytes)
        self.assertEqual(first.sha256, hashlib.sha256(first.pdf_bytes).hexdigest())
        self.assertEqual(first.filename, "PREVIEW-FE-001-001-0000099.pdf")
        self.assertIn("PREVIEW - SIN VALIDEZ FISCAL", text)
        self.assertIn("AMBIENTE: TEST", text)
        self.assertIn("QR NO DISPONIBLE", text)
        self.assertNotIn("Consulte la validez", text)
        self.assertEqual(
            self.env["fiscal.attachment"].search_count([
                ("document_id", "=", self.document.id),
            ]),
            before,
        )

    def test_preview_requires_no_authority_evidence_or_final_qr(self):
        self.assertFalse(self.document.transmission_ids)
        self.assertFalse(self.env["fiscal.attachment"].search([
            ("document_id", "=", self.document.id),
            ("attachment_type", "in", ("paraguay_qr_payload", "paraguay_kude_pdf")),
        ]))
        self.assertTrue(self.service.render(document=self.document).pdf_bytes)

    def test_accepted_document_preview_remains_distinct_from_delivery(self):
        self.document.with_context(
            einvoice_skip_fiscal_document_lock=True
        ).write({"state": "accepted", "authority_status": "local_demo"})
        preview = self.service.render(document=self.document)
        self.assertIn("PREVIEW", self._text(preview.pdf_bytes))
        with self.assertRaisesRegex(ValidationError, "acceptance evidence"):
            PyFiscalDocumentDeliveryService(self.env).resolve(document=self.document)

    def test_invalid_incomplete_and_cancelled_documents_are_blocked(self):
        self.payload_attachment.unlink()
        with self.assertRaisesRegex(ValidationError, "payload is missing"):
            self.service.render(document=self.document)
        self.payload_attachment = self.env["fiscal.attachment"].sudo(
        ).create_json_payload_attachment(
            self.document,
            "paraguay_payload_json",
            f"{self.document.uuid}-payload.json",
            {"version": "150"},
        )
        with self.assertRaisesRegex(ValidationError, "incomplete"):
            self.service.render(document=self.document)
        self.document.with_context(
            einvoice_skip_fiscal_document_lock=True
        ).write({"state": "cancelled"})
        with self.assertRaisesRegex(ValidationError, "non-cancelled"):
            self.service.render(document=self.document)

    def test_tenant_isolation_and_authenticated_separate_route(self):
        denied_document = self.document.with_user(self.denied_user)
        with self.assertRaises(AccessError):
            PyKudePreviewService(denied_document.env).render(document=denied_document)
        routing = PyFiscalDocumentPreviewController.preview.original_routing
        self.assertEqual(routing["auth"], "user")
        self.assertIn("/einvoice_py/preview/", routing["routes"][0])
        self.assertNotIn("/delivery/", routing["routes"][0])

    def test_preview_result_and_pdf_do_not_expose_secrets(self):
        result = self.service.render(document=self.document)
        serialized = repr(result)
        pdf_text = self._text(result.pdf_bytes)
        for forbidden in (
            "CSC",
            "PKCS12",
            "private key",
            "password",
            "authority_response",
            "certificate",
        ):
            self.assertNotIn(forbidden.lower(), (serialized + pdf_text).lower())

    def test_model_action_uses_preview_route(self):
        action = self.document.action_preview_paraguay_kude()
        self.assertEqual(
            action["url"],
            f"/einvoice_py/preview/{self.document.uuid}/kude",
        )
        self.assertNotIn("delivery", action["url"])
