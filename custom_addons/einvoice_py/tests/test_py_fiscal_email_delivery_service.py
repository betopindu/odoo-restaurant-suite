import hashlib
from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError

from odoo.addons.einvoice_py.services.py_fiscal_email_delivery_service import (
    PyFiscalEmailDeliveryService,
)
from odoo.addons.einvoice_py.tests.test_py_fiscal_document_delivery_service import (
    TestPyFiscalDocumentDeliveryService,
)


class TestPyFiscalEmailDeliveryService(TestPyFiscalDocumentDeliveryService):
    def setUp(self):
        super().setUp()
        self.env.company.email = "fiscal-sender@example.test"
        self.operator = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Fiscal email operator",
            "login": f"fiscal-email-{self.id()}",
            "email": "operator@example.test",
            "company_id": self.env.company.id,
            "company_ids": [(6, 0, [self.env.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("einvoice_py.group_py_fiscal_operator").id,
            ])],
            "allowed_fiscal_tenant_ids": [(6, 0, [self.tenant.id])],
        })

    def _email_service(self, user=None):
        env = self.env(user=user or self.operator)
        return PyFiscalEmailDeliveryService(
            env,
            delivery_service=self.service.__class__(
                env,
                signature_verification_service=self.service.signature_verification_service,
            ),
        )

    def test_manual_delivery_queues_exact_authoritative_pdf_and_xml(self):
        delivery = self._email_service().enqueue(
            document=self.document.with_user(self.operator), mode="manual"
        )

        self.assertEqual(delivery.mail_id.state, "outgoing")
        self.assertEqual(delivery.recipient_email, "receiver@example.test")
        self.assertEqual(delivery.pdf_sha256, self.pdf.sha256)
        self.assertEqual(delivery.xml_sha256, self.xml.sha256)
        self.assertEqual(
            sorted(delivery.mail_id.attachment_ids.mapped("name")),
            ["FE-001-001-0000006.pdf", "FE-001-001-0000006.xml"],
        )

    def test_manual_delivery_outgoing_mime_contains_pdf_and_xml(self):
        delivery = self._email_service().enqueue(
            document=self.document.with_user(self.operator), mode="manual"
        )

        outgoing = delivery.mail_id._prepare_outgoing_list()

        self.assertEqual(len(outgoing), 1)
        attachments = {
            name: (content, mimetype)
            for name, content, mimetype in outgoing[0]["attachments"]
        }
        self.assertEqual(
            sorted(attachments),
            ["FE-001-001-0000006.pdf", "FE-001-001-0000006.xml"],
        )
        self.assertEqual(attachments["FE-001-001-0000006.pdf"][1], "application/pdf")
        # Odoo deliberately downgrades XML uploaded by non-technical users to
        # text/plain as an XSS safeguard.  The bytes and recipient filename are
        # authoritative and must still be present in the outgoing MIME.
        self.assertIn(
            attachments["FE-001-001-0000006.xml"][1],
            ("application/xml", "text/xml", "text/plain"),
        )
        self.assertEqual(
            hashlib.sha256(attachments["FE-001-001-0000006.pdf"][0]).hexdigest(),
            self.pdf.sha256,
        )
        self.assertEqual(
            hashlib.sha256(attachments["FE-001-001-0000006.xml"][0]).hexdigest(),
            self.xml.sha256,
        )

    def test_manual_delivery_fails_closed_when_mime_loses_attachments(self):
        mail_model = type(self.env["mail.mail"])
        with patch.object(
            mail_model,
            "_prepare_outgoing_list",
            return_value=[{"attachments": []}],
        ):
            with self.assertRaisesRegex(ValidationError, "authoritative KuDE PDF and XML"):
                self._email_service().enqueue(
                    document=self.document.with_user(self.operator), mode="manual"
                )

    def test_recipient_uses_immutable_snapshot_not_current_partner(self):
        partner = self.env["res.partner"].create({
            "name": "Changed partner", "email": "changed@example.test"
        })
        self.document.partner_id = partner
        self.document.customer_email = "snapshot@example.test"

        prepared = self._email_service().prepare(document=self.document.with_user(self.operator))

        self.assertEqual(prepared.recipient_email, "snapshot@example.test")

    def test_missing_snapshot_email_fails_closed(self):
        self.document.customer_email = False
        with self.assertRaisesRegex(ValidationError, "receiver snapshot"):
            self._email_service().prepare(document=self.document.with_user(self.operator))

    def test_non_operator_cannot_queue_manual_delivery(self):
        with self.assertRaises(AccessError):
            self._email_service(self.allowed_user).enqueue(
                document=self.document.with_user(self.allowed_user), mode="manual"
            )
        with self.assertRaises(AccessError):
            self.document.with_user(
                self.allowed_user
            ).action_open_py_fiscal_email_delivery()

    def test_opening_and_cancelling_wizard_create_no_mail_or_delivery(self):
        document = self.document.with_user(self.operator)
        before_mail = self.env["mail.mail"].sudo().search_count([])
        with patch(
            "odoo.addons.einvoice_py.services.py_fiscal_document_delivery_service.PyFiscalDocumentDeliveryService._validate_final_rde"
        ):
            action = document.action_open_py_fiscal_email_delivery()

        self.assertEqual(action["res_model"], "py.fiscal.email.delivery.wizard")
        self.assertEqual(self.env["py.fiscal.email.delivery"].sudo().search_count([
            ("document_id", "=", self.document.id),
        ]), 0)
        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), before_mail)

    def test_confirmation_is_idempotent_for_same_wizard(self):
        document = self.document.with_user(self.operator)
        with patch(
            "odoo.addons.einvoice_py.services.py_fiscal_document_delivery_service.PyFiscalDocumentDeliveryService._validate_final_rde"
        ):
            action = document.action_open_py_fiscal_email_delivery()
        wizard = self.env["py.fiscal.email.delivery.wizard"].with_user(
            self.operator
        ).browse(action["res_id"])

        with patch(
            "odoo.addons.einvoice_py.services.py_fiscal_document_delivery_service.PyFiscalDocumentDeliveryService._validate_final_rde"
        ):
            wizard.action_confirm()
        first = wizard.delivery_id
        with patch(
            "odoo.addons.einvoice_py.services.py_fiscal_document_delivery_service.PyFiscalDocumentDeliveryService._validate_final_rde"
        ):
            wizard.action_confirm()

        self.assertEqual(wizard.delivery_id, first)
        self.assertEqual(self.env["py.fiscal.email.delivery"].sudo().search_count([
            ("document_id", "=", self.document.id),
        ]), 1)

    def test_automatic_delivery_is_disabled_by_default(self):
        result = self._email_service().enqueue_automatic_if_enabled(
            document=self.document.with_user(self.operator)
        )
        self.assertFalse(result)
        self.assertFalse(self.document.py_email_delivery_ids)

    def test_automatic_delivery_queues_once_when_enabled(self):
        self.env.company.py_auto_email_accepted_fiscal_documents = True
        service = self._email_service()
        first = service.enqueue_automatic_if_enabled(
            document=self.document.with_user(self.operator)
        )
        second = service.enqueue_automatic_if_enabled(
            document=self.document.with_user(self.operator)
        )
        self.assertEqual(first, second)
        self.assertEqual(first.mode, "automatic")
        self.assertEqual(len(self.document.py_email_delivery_ids), 1)

    def test_automatic_delivery_honors_channel_suppression(self):
        self.env.company.py_auto_email_accepted_fiscal_documents = True
        self.document.py_email_delivery_policy = "suppressed"

        result = self._email_service().enqueue_automatic_if_enabled(
            document=self.document.with_user(self.operator)
        )

        self.assertFalse(result)
        self.assertFalse(self.document.py_email_delivery_ids)

    def test_email_failure_never_changes_accepted_fiscal_state(self):
        self.env.company.py_auto_email_accepted_fiscal_documents = True
        self.document.customer_email = False
        result = self._email_service().enqueue_automatic_if_enabled(
            document=self.document.with_user(self.operator)
        )
        self.assertEqual(result.preparation_status, "failed")
        self.assertFalse(result.mail_id)
        self.assertEqual(self.document.state, "accepted")
        self.assertEqual(self.document.authority_status, "0260")

    def test_queueing_never_sends_mail_or_contacts_transport(self):
        with patch("odoo.addons.mail.models.mail_mail.MailMail.send") as send:
            self._email_service().enqueue(
                document=self.document.with_user(self.operator), mode="manual"
            )
        send.assert_not_called()

    def test_manual_request_identity_prevents_duplicate_email_queue(self):
        service = self._email_service()
        document = self.document.with_user(self.operator)
        first = service.enqueue(
            document=document,
            mode="manual",
            request_key="pos:42:request-0001",
        )
        second = service.enqueue(
            document=document,
            mode="manual",
            request_key="pos:42:request-0001",
        )

        self.assertEqual(first, second)
        self.assertEqual(first.request_key, "pos:42:request-0001")
        self.assertEqual(self.env["mail.mail"].sudo().search_count([
            ("id", "=", first.mail_id.id),
        ]), 1)
