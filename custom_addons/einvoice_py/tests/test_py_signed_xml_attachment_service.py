import base64
import hashlib
import json

from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_signed_xml_attachment_service import (
    PySignedXmlAttachmentService,
)


class TestPySignedXmlAttachmentService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"
    SIGNED_XML = (
        b"<?xml version='1.0' encoding='UTF-8'?>"
        b"<rDE><DE Id='01444444017001001001452822017012515873260988'/>"
        b"<Signature>fixture</Signature></rDE>"
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "Signed XML Attachment Tenant",
            "code": "signed-xml-attachment",
            "company_id": cls.env.company.id,
        })
        cls.service = PySignedXmlAttachmentService(cls.env)

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "Signed XML Attachment Document",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Test Customer",
            "amount_total": 100,
            "idempotency_key": self.id(),
            "country_identifier": self.CDC,
        })

    def _metadata(self):
        return {
            "cdc": self.CDC,
            "digest_value": "digest-fixture",
            "certificate_fingerprint_sha256": "a" * 64,
            "signing_time": "2026-06-18T12:34:56",
            "ignored": "not persisted",
        }

    def _persist_signed_xml(self):
        return self.service.persist(
            document=self.document,
            signed_xml_bytes=self.SIGNED_XML,
            filename=f"{self.document.uuid}-paraguay-signed.xml",
            metadata=self._metadata(),
        )

    def _create_payload_attachment(self):
        return self.env["fiscal.attachment"].sudo().create_json_payload_attachment(
            self.document,
            "paraguay_payload_json",
            f"{self.document.uuid}-paraguay-payload.json",
            {"cdc": self.CDC},
        )

    def _create_unsigned_xml_attachment(self):
        unsigned_xml = b"<rDE><DE Id='%s'/></rDE>" % self.CDC.encode("ascii")
        filename = f"{self.document.uuid}-paraguay-unsigned.xml"
        ir_attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(unsigned_xml),
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
            "sha256": hashlib.sha256(unsigned_xml).hexdigest(),
            "is_sensitive": True,
        })

    def test_signed_xml_attachment_created(self):
        attachment = self._persist_signed_xml()

        self.assertEqual(attachment.attachment_type, "paraguay_xml_signed")
        self.assertEqual(attachment.mimetype, "application/xml")
        self.assertTrue(attachment.ir_attachment_id)
        self.assertEqual(
            base64.b64decode(attachment.ir_attachment_id.datas),
            self.SIGNED_XML,
        )

    def test_signed_xml_attachment_has_hash_and_sensitive_flag(self):
        attachment = self._persist_signed_xml()

        self.assertEqual(
            attachment.sha256,
            hashlib.sha256(self.SIGNED_XML).hexdigest(),
        )
        self.assertTrue(attachment.is_sensitive)

    def test_signed_xml_metadata_is_stored(self):
        attachment = self._persist_signed_xml()
        metadata = json.loads(attachment.metadata_json)

        self.assertEqual(metadata, {
            "artifact_status": "current",
            "cdc": self.CDC,
            "certificate_fingerprint_sha256": "a" * 64,
            "digest_value": "digest-fixture",
            "signing_time": "2026-06-18T12:34:56",
        })

    def test_retry_returns_existing_signed_xml_attachment(self):
        first = self._persist_signed_xml()
        second = self._persist_signed_xml()
        attachments = self.env["fiscal.attachment"].search([
            ("document_id", "=", self.document.id),
            ("attachment_type", "=", "paraguay_xml_signed"),
        ])

        self.assertEqual(first, second)
        self.assertEqual(len(attachments), 1)

    def test_changed_signed_xml_supersedes_previous_attachment(self):
        first = self._persist_signed_xml()
        changed_xml = self.SIGNED_XML.replace(b"fixture", b"corrected-fixture")

        second = self.service.persist(
            document=self.document,
            signed_xml_bytes=changed_xml,
            filename=f"{self.document.uuid}-paraguay-signed-corrected.xml",
            metadata={**self._metadata(), "signing_time": "2026-06-18T12:35:56"},
        )

        self.assertNotEqual(first, second)
        self.assertEqual(
            json.loads(first.metadata_json),
            {
                "artifact_status": "superseded",
                "cdc": self.CDC,
                "certificate_fingerprint_sha256": "a" * 64,
                "digest_value": "digest-fixture",
                "signing_time": "2026-06-18T12:34:56",
                "superseded_by_attachment_id": second.id,
            },
        )
        self.assertEqual(
            json.loads(second.metadata_json)["supersedes_attachment_id"],
            first.id,
        )
        self.assertEqual(self.service.current(document=self.document), second)
        self.assertEqual(base64.b64decode(first.ir_attachment_id.datas), self.SIGNED_XML)
        self.assertEqual(base64.b64decode(second.ir_attachment_id.datas), changed_xml)

    def test_rejected_document_can_persist_corrected_signed_artifact(self):
        first = self._persist_signed_xml()
        self.document.write({"state": "rejected"})
        corrected_xml = self.SIGNED_XML.replace(b"fixture", b"rejected-correction")

        corrected = self.service.persist(
            document=self.document,
            signed_xml_bytes=corrected_xml,
            filename=f"{self.document.uuid}-paraguay-signed-corrected.xml",
            metadata=self._metadata(),
        )

        self.assertNotEqual(corrected, first)
        self.assertTrue(first.exists())
        self.assertEqual(
            json.loads(first.metadata_json)["artifact_status"],
            "superseded",
        )
        self.assertEqual(self.service.current(document=self.document), corrected)

    def test_unsigned_and_payload_attachments_remain_separate(self):
        payload_attachment = self._create_payload_attachment()
        unsigned_attachment = self._create_unsigned_xml_attachment()

        signed_attachment = self._persist_signed_xml()

        self.assertNotEqual(signed_attachment, payload_attachment)
        self.assertNotEqual(signed_attachment, unsigned_attachment)
        self.assertEqual(
            set(self.env["fiscal.attachment"].search([
                ("document_id", "=", self.document.id),
            ]).mapped("attachment_type")),
            {
                "paraguay_payload_json",
                "paraguay_xml_unsigned",
                "paraguay_xml_signed",
            },
        )
        self.assertTrue(payload_attachment.exists())
        self.assertTrue(unsigned_attachment.exists())
