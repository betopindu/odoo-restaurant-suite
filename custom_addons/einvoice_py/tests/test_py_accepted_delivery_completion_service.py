import base64
import hashlib
import json
from types import SimpleNamespace

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_accepted_delivery_completion_service import (
    PyAcceptedDeliveryCompletionService,
)
from odoo.addons.einvoice_py.services.py_fiscal_document_delivery_service import (
    PyFiscalDocumentDeliveryService,
)
from odoo.addons.einvoice_py.services.py_qr_payload_attachment_service import (
    PyQrPayloadAttachmentService,
)
from odoo.addons.einvoice_py.services.py_source_artifact_service import (
    PySourceArtifactService,
)


class _ValidSignature:
    def verify(self, **_kwargs):
        return {"valid": True}


class _ValidXsd:
    def validate_final_signed_xml(self, _content):
        return {"valid": True, "errors": []}


class _PersistingKude:
    def __init__(self, env, payload_attachment, qr_attachment, cdc):
        self.env = env
        self.payload_attachment = payload_attachment
        self.qr_attachment = qr_attachment
        self.cdc = cdc
        self.calls = 0

    def generate(self, *, document):
        self.calls += 1
        content = b"%PDF-1.4\nauthoritative-kude\n%%EOF"
        digest = hashlib.sha256(content).hexdigest()
        existing = self.env["fiscal.attachment"].sudo().search([
            ("document_id", "=", document.id),
            ("attachment_type", "=", "paraguay_kude_pdf"),
            ("sha256", "=", digest),
        ], limit=1)
        if not existing:
            ir_attachment = self.env["ir.attachment"].sudo().create({
                "name": "authoritative-kude.pdf",
                "datas": base64.b64encode(content),
                "mimetype": "application/pdf",
                "res_model": "fiscal.document",
                "res_id": document.id,
            })
            existing = self.env["fiscal.attachment"].sudo().create({
                "name": "authoritative-kude.pdf",
                "document_id": document.id,
                "attachment_type": "paraguay_kude_pdf",
                "mimetype": "application/pdf",
                "filename": "authoritative-kude.pdf",
                "ir_attachment_id": ir_attachment.id,
                "sha256": digest,
                "is_sensitive": True,
                "metadata_json": json.dumps({
                    "artifact_status": "current",
                    "cdc": self.cdc,
                    "payload_attachment_id": self.payload_attachment.id,
                    "payload_sha256": self.payload_attachment.sha256,
                    "qr_attachment_id": self.qr_attachment.id,
                    "qr_payload_sha256": self.qr_attachment.sha256,
                }),
            })
        return SimpleNamespace(
            attachment_id=existing.id,
            payload_attachment_id=self.payload_attachment.id,
            qr_attachment_id=self.qr_attachment.id,
            sha256=digest,
            cdc=self.cdc,
        )


class TestPyAcceptedDeliveryCompletionService(TransactionCase):
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
            "name": "Accepted Delivery Completion Tenant",
            "code": "accepted-delivery-completion",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "Accepted completion invoice",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Receiver",
            "amount_total": 100,
            "idempotency_key": self.id(),
            "state": "accepted",
            "authority_status": "0260",
            "py_cdc": self.CDC,
            "country_identifier": self.CDC,
            "py_full_number": "001-001-0000007",
        })
        self.env["fiscal.transmission"].create({
            "document_id": self.document.id,
            "transmission_type": "submit",
            "state": "accepted",
            "country_code": "PY",
            "environment": "test",
            "country_identifier": self.CDC,
            "authority_status_code": "0260",
            "request_hash": "b" * 64,
            "response_hash": "c" * 64,
            "metadata_json": json.dumps({"ambiguous": False}),
        })
        source = PySourceArtifactService(self.env)
        self.payload = source.persist_payload(
            document=self.document,
            payload={"cdc": self.CDC, "document": {"py_cdc": self.CDC}},
        )
        self.unsigned = source.persist_unsigned_xml(
            document=self.document,
            unsigned_xml_bytes=b"<unsigned/>",
            payload_attachment=self.payload,
        )
        self.signed = self._attachment(
            "paraguay_xml_signed",
            b"<signed/>",
            {
                "artifact_status": "current",
                "cdc": self.CDC,
                "payload_attachment_id": self.payload.id,
                "payload_sha256": self.payload.sha256,
                "unsigned_attachment_id": self.unsigned.id,
                "unsigned_sha256": self.unsigned.sha256,
            },
        )
        self.qr = PyQrPayloadAttachmentService(self.env).persist(
            document=self.document,
            qr_payload=self.QR_URL,
            qr_hash=self.QR_HASH,
            signed_attachment_id=self.signed.id,
            signed_xml_sha256=self.signed.sha256,
            digest_value="digest",
        )
        self.rde = self._attachment(
            "paraguay_rde_final",
            self._rde(),
            {
                "artifact_status": "current",
                "cdc": self.CDC,
                "signed_attachment_id": self.signed.id,
                "signed_xml_sha256": self.signed.sha256,
                "qr_attachment_id": self.qr.id,
                "qr_sha256": self.qr.sha256,
            },
        )
        delivery = PyFiscalDocumentDeliveryService(
            self.env, signature_verification_service=_ValidSignature()
        )
        self.kude = _PersistingKude(self.env, self.payload, self.qr, self.CDC)
        self.service = PyAcceptedDeliveryCompletionService(
            self.env,
            delivery_service=delivery,
            kude_service=self.kude,
            signature_service=_ValidSignature(),
            xsd_service=_ValidXsd(),
        )

    def _attachment(self, attachment_type, content, metadata):
        ir_attachment = self.env["ir.attachment"].sudo().create({
            "name": attachment_type,
            "datas": base64.b64encode(content),
            "mimetype": "application/xml",
            "res_model": "fiscal.document",
            "res_id": self.document.id,
        })
        return self.env["fiscal.attachment"].sudo().create({
            "name": attachment_type,
            "document_id": self.document.id,
            "attachment_type": attachment_type,
            "mimetype": "application/xml",
            "filename": f"{attachment_type}.xml",
            "ir_attachment_id": ir_attachment.id,
            "sha256": hashlib.sha256(content).hexdigest(),
            "is_sensitive": True,
            "metadata_json": json.dumps(metadata),
        })

    def _rde(self):
        ns = PyAcceptedDeliveryCompletionService.SIFEN_NS
        root = etree.Element(f"{{{ns}}}rDE", nsmap={None: ns})
        etree.SubElement(root, f"{{{ns}}}dVerFor").text = "150"
        etree.SubElement(root, f"{{{ns}}}DE", Id=self.CDC)
        etree.SubElement(
            root, "{http://www.w3.org/2000/09/xmldsig#}Signature"
        )
        group = etree.SubElement(root, f"{{{ns}}}gCamFuFD")
        etree.SubElement(group, f"{{{ns}}}dCarQR").text = self.QR_URL
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    def test_missing_authoritative_kude_is_completed_offline_and_idempotently(self):
        first = self.service.ensure(document=self.document)
        second = self.service.ensure(document=self.document)

        self.assertEqual(first.attachment_id, second.attachment_id)
        self.assertEqual(first.payload_attachment_id, self.payload.id)
        self.assertEqual(first.qr_attachment_id, self.qr.id)
        self.assertEqual(first.cdc, self.CDC)
        self.assertEqual(self.kude.calls, 2)
        self.assertEqual(
            self.env["fiscal.attachment"].search_count([
                ("document_id", "=", self.document.id),
                ("attachment_type", "=", "paraguay_kude_pdf"),
            ]),
            1,
        )

    def test_tampered_chain_blocks_completion(self):
        self.signed.sha256 = "0" * 64

        with self.assertRaisesRegex(ValidationError, "integrity"):
            self.service.ensure(document=self.document)

        self.assertEqual(self.kude.calls, 0)

    def test_multiple_current_signed_artifacts_block_completion(self):
        self._attachment(
            "paraguay_xml_signed",
            b"<different-signed/>",
            {"artifact_status": "current", "cdc": self.CDC},
        )

        with self.assertRaisesRegex(ValidationError, "lifecycle"):
            self.service.ensure(document=self.document)

        self.assertEqual(self.kude.calls, 0)

    def test_nonaccepted_document_is_not_completed(self):
        self.document.with_context(einvoice_skip_fiscal_document_lock=True).write({
            "state": "rejected",
        })

        with self.assertRaisesRegex(ValidationError, "Only accepted"):
            self.service.ensure(document=self.document)

        self.assertEqual(self.kude.calls, 0)
