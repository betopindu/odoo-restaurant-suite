import base64
import hashlib
import json

from lxml import etree

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_fiscal_document_delivery_service import (
    PyFiscalDocumentDeliveryService,
)


class _SignatureVerificationStub:
    def verify(self, **_kwargs):
        return {"valid": True}


class TestPyFiscalDocumentDeliveryService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "Delivery Tenant",
            "code": "delivery-tenant",
            "company_id": cls.env.company.id,
        })
        cls.other_tenant = cls.env["fiscal.tenant"].create({
            "name": "Other Delivery Tenant",
            "code": "other-delivery-tenant",
            "company_id": cls.env.company.id,
        })
        cls.allowed_user = cls._user("delivery-allowed", cls.tenant)
        cls.denied_user = cls._user("delivery-denied", cls.other_tenant)
        cls.other_company = cls.env["res.company"].create({"name": "Delivery Other Company"})
        cls.company_denied_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create({
            "name": "delivery-company-denied",
            "login": "delivery-company-denied",
            "email": "delivery-company-denied@example.test",
            "company_id": cls.other_company.id,
            "company_ids": [(6, 0, [cls.other_company.id])],
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
            "allowed_fiscal_tenant_ids": [(6, 0, [cls.tenant.id])],
        })

    @classmethod
    def _user(cls, login, tenant):
        return cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": login,
            "login": login,
            "email": f"{login}@example.test",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
            "allowed_fiscal_tenant_ids": [(6, 0, [tenant.id])],
        })

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "Accepted delivery invoice",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Delivery Receiver",
            "customer_email": "receiver@example.test",
            "amount_total": 100,
            "idempotency_key": self.id(),
            "state": "accepted",
            "authority_status": "0260",
            "py_cdc": self.CDC,
            "country_identifier": self.CDC,
            "py_full_number": "001-001-0000006",
        })
        self.pdf = self._attachment(
            "paraguay_kude_pdf",
            b"%PDF-1.4\nrecipient-kude\n%%EOF",
            "application/pdf",
            {"artifact_status": "current", "cdc": self.CDC},
        )
        self.xml = self._attachment(
            "paraguay_rde_final",
            self._final_rde(),
            "application/xml",
            {"artifact_status": "current", "cdc": self.CDC},
        )
        self.acceptance = self._transmission(
            state="accepted",
            authority_status_code="0260",
        )
        self.service = PyFiscalDocumentDeliveryService(
            self.env,
            signature_verification_service=_SignatureVerificationStub(),
        )

    def _attachment(self, attachment_type, content, mimetype, metadata):
        ir_attachment = self.env["ir.attachment"].sudo().create({
            "name": "internal-artifact",
            "datas": base64.b64encode(content),
            "mimetype": mimetype,
            "res_model": "fiscal.document",
            "res_id": self.document.id,
        })
        return self.env["fiscal.attachment"].sudo().create({
            "name": "internal-artifact",
            "document_id": self.document.id,
            "attachment_type": attachment_type,
            "mimetype": mimetype,
            "filename": "internal-artifact",
            "ir_attachment_id": ir_attachment.id,
            "sha256": hashlib.sha256(content).hexdigest(),
            "is_sensitive": True,
            "metadata_json": json.dumps(metadata),
        })

    def _final_rde(self, marker="current"):
        sifen = PyFiscalDocumentDeliveryService.SIFEN_NS
        ds = PyFiscalDocumentDeliveryService.DS_NS
        root = etree.Element(f"{{{sifen}}}rDE", nsmap={None: sifen})
        etree.SubElement(root, f"{{{sifen}}}dVerFor").text = "150"
        de = etree.SubElement(root, f"{{{sifen}}}DE", Id=self.CDC)
        etree.SubElement(de, f"{{{sifen}}}dDVId").text = self.CDC[-1]
        etree.SubElement(root, f"{{{ds}}}Signature").text = marker
        qr = etree.SubElement(root, f"{{{sifen}}}gCamFuFD")
        etree.SubElement(qr, f"{{{sifen}}}dCarQR").text = "https://example.test/qr"
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    def _transmission(self, **overrides):
        values = {
            "document_id": self.document.id,
            "transmission_type": "submit",
            "state": "rejected",
            "country_code": "PY",
            "environment": "test",
            "country_identifier": self.CDC,
            "authority_status_code": "1300",
            "request_hash": "a" * 64,
            "response_hash": "b" * 64,
            "metadata_json": json.dumps({"ambiguous": False}),
        }
        values.update(overrides)
        return self.env["fiscal.transmission"].create(values)

    def test_accepted_document_resolves_current_pdf_and_final_xml(self):
        bundle = self.service.resolve(document=self.document)

        self.assertEqual(bundle.pdf.fiscal_attachment_id, self.pdf.id)
        self.assertEqual(bundle.xml.fiscal_attachment_id, self.xml.id)
        self.assertEqual(bundle.document["cdc"], self.CDC)
        self.assertEqual(bundle.document["authority_state"], "0260")
        self.assertEqual(bundle.pdf.filename, "FE-001-001-0000006.pdf")
        self.assertEqual(bundle.xml.filename, "FE-001-001-0000006.xml")
        pdf_action = self.document.action_download_paraguay_kude()
        xml_action = self.document.action_download_paraguay_xml()
        self.assertEqual(
            pdf_action["url"],
            f"/einvoice_py/delivery/{self.document.uuid}/pdf",
        )
        self.assertEqual(
            xml_action["url"],
            f"/einvoice_py/delivery/{self.document.uuid}/xml",
        )
        self.assertNotIn(str(self.pdf.id), pdf_action["url"])
        self.assertNotIn(str(self.xml.id), xml_action["url"])

    def test_authoritative_xml_resolves_independently_when_kude_is_missing(self):
        self.pdf.unlink()

        xml = self.service.resolve_file(document=self.document, file_kind="xml")

        self.assertEqual(xml.fiscal_attachment_id, self.xml.id)
        self.assertEqual(xml.filename, "FE-001-001-0000006.xml")
        with self.assertRaisesRegex(ValidationError, "KuDE PDF is missing"):
            self.service.resolve_file(document=self.document, file_kind="pdf")

    def test_nonaccepted_documents_are_not_deliverable(self):
        for state in ("draft", "ready", "signed", "submitted", "rejected", "manual_review", "cancelled"):
            with self.subTest(state=state):
                self.document.with_context(
                    einvoice_skip_fiscal_document_lock=True
                ).write({"state": state})
                with self.assertRaisesRegex(ValidationError, "Only accepted"):
                    self.service.resolve(document=self.document)

    def test_accepted_state_without_authority_evidence_is_blocked(self):
        self.acceptance.unlink()
        with self.assertRaisesRegex(ValidationError, "acceptance evidence"):
            self.service.resolve(document=self.document)

    def test_forged_local_accepted_state_is_blocked(self):
        self.acceptance.unlink()
        self.document.with_context(
            einvoice_skip_fiscal_document_lock=True
        ).write({"metadata_json": json.dumps({"authority_source": "local_demo"})})
        with self.assertRaisesRegex(ValidationError, "acceptance evidence"):
            self.service.prepare_email(document=self.document)

    def test_rejected_or_ambiguous_submission_is_blocked(self):
        self.acceptance.unlink()
        self._transmission()
        with self.assertRaisesRegex(ValidationError, "acceptance evidence"):
            self.service.resolve(document=self.document)
        self._transmission(
            state="accepted",
            authority_status_code="0260",
            metadata_json=json.dumps({"ambiguous": True}),
        )
        with self.assertRaisesRegex(ValidationError, "acceptance evidence"):
            self.service.resolve(document=self.document)

    def test_incoherent_accepted_transmission_is_blocked(self):
        for field, value in (
            ("country_identifier", "0" * 44),
            ("environment", "production"),
            ("country_code", "CR"),
        ):
            with self.subTest(field=field):
                original = self.acceptance[field]
                self.acceptance.write({field: value})
                with self.assertRaisesRegex(ValidationError, "acceptance evidence"):
                    self.service.resolve(document=self.document)
                self.acceptance.write({field: original})

        self.acceptance.write({"request_hash": ""})
        with self.assertRaisesRegex(ValidationError, "acceptance evidence"):
            self.service.resolve(document=self.document)

    def test_document_authority_status_must_match_direct_evidence(self):
        self.document.with_context(
            einvoice_skip_fiscal_document_lock=True
        ).write({"authority_status": "0422"})
        with self.assertRaisesRegex(ValidationError, "acceptance evidence"):
            self.service.resolve(document=self.document)

    def test_accepted_transmission_for_another_document_is_blocked(self):
        self.acceptance.unlink()
        other = self.document.copy({
            "name": "Other accepted document",
            "idempotency_key": f"{self.id()}-other",
        })
        self.env["fiscal.transmission"].create({
            "document_id": other.id,
            "transmission_type": "submit",
            "state": "accepted",
            "country_code": "PY",
            "environment": "test",
            "country_identifier": self.CDC,
            "authority_status_code": "0260",
        })
        with self.assertRaisesRegex(ValidationError, "acceptance evidence"):
            self.service.resolve(document=self.document)

    def test_authoritative_consulta_reconciliation_is_eligible(self):
        self.acceptance.unlink()
        self.document.with_context(
            einvoice_skip_fiscal_document_lock=True
        ).write({"authority_status": "0422"})
        original = self._transmission(
            state="manual_review",
            authority_status_code="",
            metadata_json=json.dumps({"ambiguous": True}),
        )
        self._transmission(
            transmission_type="status_query",
            state="accepted",
            authority_status_code="0422",
            metadata_json=json.dumps({
                "result_category": "approved",
                "normalized_response": {"approved": True},
                "response_structure": {"returned_cdc": self.CDC},
                "original_submission_ids": [original.id],
            }),
        )
        self.assertEqual(self.service.resolve(document=self.document).document["cdc"], self.CDC)

    def test_direct_acceptance_remains_canonical_after_diagnostic_query(self):
        self._transmission(
            transmission_type="status_query",
            state="accepted",
            authority_status_code="0422",
            metadata_json=json.dumps({
                "result_category": "approved",
                "normalized_response": {"approved": True},
                "response_structure": {"returned_cdc": self.CDC},
            }),
        )
        self.assertEqual(self.service.resolve(document=self.document).document["cdc"], self.CDC)

    def test_incomplete_consulta_evidence_is_blocked(self):
        self.acceptance.unlink()
        self._transmission(
            transmission_type="status_query",
            state="accepted",
            authority_status_code="0422",
            metadata_json=json.dumps({
                "result_category": "approved",
                "normalized_response": {"approved": True},
            }),
        )
        with self.assertRaisesRegex(ValidationError, "acceptance evidence"):
            self.service.resolve(document=self.document)

    def test_superseded_artifacts_are_never_selected(self):
        old_pdf = self._attachment(
            "paraguay_kude_pdf",
            b"%PDF-1.4\nstale-secret\n%%EOF",
            "application/pdf",
            {"artifact_status": "superseded", "superseded_by_attachment_id": self.pdf.id},
        )
        old_xml = self._attachment(
            "paraguay_rde_final",
            self._final_rde("stale"),
            "application/xml",
            {"artifact_status": "superseded", "superseded_by_attachment_id": self.xml.id},
        )

        bundle = self.service.resolve(document=self.document)

        self.assertNotEqual(bundle.pdf.fiscal_attachment_id, old_pdf.id)
        self.assertNotEqual(bundle.xml.fiscal_attachment_id, old_xml.id)
        self.assertNotIn(b"stale-secret", bundle.pdf.content)
        self.assertNotIn(b"stale", bundle.xml.content)

    def test_missing_pdf_or_final_xml_is_blocked_safely(self):
        self.pdf.unlink()
        with self.assertRaisesRegex(ValidationError, "KuDE PDF is missing"):
            self.service.resolve(document=self.document)

        self.pdf = self._attachment(
            "paraguay_kude_pdf", b"%PDF-1.4\n%%EOF", "application/pdf",
            {"artifact_status": "current"},
        )
        self.xml.unlink()
        with self.assertRaisesRegex(ValidationError, "final signed XML is missing"):
            self.service.resolve(document=self.document)

    def test_pre_qr_signed_xml_is_not_deliverable(self):
        self.xml.unlink()
        sifen = self.service.SIFEN_NS
        root = etree.Element(f"{{{sifen}}}rDE", nsmap={None: sifen})
        etree.SubElement(root, f"{{{sifen}}}DE", Id=self.CDC)
        etree.SubElement(root, f"{{{self.service.DS_NS}}}Signature")
        self._attachment(
            "paraguay_rde_final", etree.tostring(root), "application/xml",
            {"artifact_status": "current"},
        )
        with self.assertRaisesRegex(ValidationError, "not complete"):
            self.service.resolve(document=self.document)

    def test_repeated_resolution_is_idempotent(self):
        before = len(self.document.attachment_ids)
        first = self.service.resolve(document=self.document)
        second = self.service.resolve(document=self.document)
        self.assertEqual(first, second)
        self.assertEqual(len(self.document.attachment_ids), before)

    def test_recipient_filename_rejects_unsafe_document_number(self):
        self.document.with_context(
            einvoice_skip_fiscal_document_lock=True
        ).write({"py_full_number": "../../secret"})
        with self.assertRaisesRegex(ValidationError, "safe document number"):
            self.service.resolve(document=self.document)

    def test_email_preparation_contains_only_recipient_pdf_and_xml(self):
        prepared = self.service.prepare_email(document=self.document)
        self.assertEqual(prepared.recipient_email, "receiver@example.test")
        self.assertEqual([item.kind for item in prepared.attachments], ["pdf", "xml"])
        serialized = repr(prepared)
        for forbidden in ("CSC", "PKCS12", "private key", "payload_json", "qr_payload"):
            self.assertNotIn(forbidden, serialized)
        self.assertNotIn("recipient-kude", serialized)

    def test_tenant_record_rules_prevent_unauthorized_resolution(self):
        allowed_document = self.document.with_user(self.allowed_user)
        allowed_service = PyFiscalDocumentDeliveryService(
            allowed_document.env,
            signature_verification_service=_SignatureVerificationStub(),
        )
        self.assertEqual(allowed_service.resolve(document=allowed_document).document["cdc"], self.CDC)

        denied_document = self.document.with_user(self.denied_user)
        denied_service = PyFiscalDocumentDeliveryService(
            denied_document.env,
            signature_verification_service=_SignatureVerificationStub(),
        )
        with self.assertRaises(AccessError):
            denied_service.resolve(document=denied_document)

        company_denied = self.document.with_user(self.company_denied_user)
        company_denied_service = PyFiscalDocumentDeliveryService(
            company_denied.env,
            signature_verification_service=_SignatureVerificationStub(),
        )
        with self.assertRaises(AccessError):
            company_denied_service.resolve(document=company_denied)

    def test_no_other_sensitive_artifact_can_be_requested(self):
        payload = self._attachment(
            "paraguay_payload_json", b'{"secret":"never-deliver"}',
            "application/json", {"artifact_status": "current"},
        )
        bundle = self.service.resolve(document=self.document)
        self.assertNotEqual(bundle.pdf.fiscal_attachment_id, payload.id)
        self.assertNotEqual(bundle.xml.fiscal_attachment_id, payload.id)
        self.assertNotIn(b"never-deliver", bundle.pdf.content + bundle.xml.content)
