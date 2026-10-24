from unittest.mock import Mock

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPosFiscalSubmissionJob(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "POS Auto Submission Tenant",
            "company_id": cls.company.id,
        })
        operator_group = cls.env.ref("einvoice_py.group_py_fiscal_operator")
        cls.operator = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "POS Automatic Fiscal Operator",
            "login": "pos-auto-fiscal@example.test",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, [operator_group.id])],
            "allowed_fiscal_tenant_ids": [(6, 0, [cls.tenant.id])],
        })
        cls.issuer = cls.env["fiscal.py.issuer"].create({
            "name": "POS Auto Issuer",
            "tenant_id": cls.tenant.id,
            "company_id": cls.company.id,
            "environment": "test",
            "ruc": "80000000",
            "ruc_dv": "0",
            "taxpayer_type": "2",
        })
        cls.establishment = cls.env["fiscal.py.establishment"].create({
            "name": "POS Auto Establishment",
            "code": "001",
            "tenant_id": cls.tenant.id,
            "company_id": cls.company.id,
            "issuer_id": cls.issuer.id,
        })
        cls.point = cls.env["fiscal.py.point.of.issue"].create({
            "name": "POS Auto Point",
            "code": "001",
            "establishment_id": cls.establishment.id,
        })
        cls.unnamed = cls.env["res.partner"].create({
            "name": "POS Auto Unnamed",
            "py_sifen_receiver_profile": "unnamed_consumer",
        })
        cls.cash_journal = cls.env["account.journal"].create({
            "name": "POS Auto Cash",
            "code": "PACS",
            "type": "cash",
            "company_id": cls.company.id,
        })
        cls.cash_method = cls.env["pos.payment.method"].create({
            "name": "POS Auto Cash",
            "journal_id": cls.cash_journal.id,
            "company_id": cls.company.id,
            "py_sifen_payment_type_code": "1",
        })
        cls.config = cls.env["pos.config"].create({
            "name": "POS Automatic Submission",
            "company_id": cls.company.id,
            "py_fiscal_checkout_enabled": True,
            "py_fiscal_environment": "test",
            "py_fiscal_tenant_id": cls.tenant.id,
            "py_fiscal_establishment_id": cls.establishment.id,
            "py_fiscal_point_of_issue_id": cls.point.id,
            "py_fiscal_unnamed_partner_id": cls.unnamed.id,
            "payment_method_ids": [(6, 0, [cls.cash_method.id])],
        })
        cls.config.write({
            "py_fiscal_auto_submit_enabled": True,
            "py_fiscal_auto_submit_user_id": cls.operator.id,
        })
        cls.session = cls.env["pos.session"].create({
            "config_id": cls.config.id,
            "user_id": cls.env.user.id,
        })

    def _records(self, suffix):
        order = self.env["pos.order"].create({
            "name": f"Auto fiscal {suffix}",
            "pos_reference": f"Auto fiscal {suffix}",
            "session_id": self.session.id,
            "config_id": self.config.id,
            "company_id": self.company.id,
            "amount_total": 100,
            "amount_tax": 0,
            "amount_paid": 100,
            "amount_return": 0,
            "py_fiscal_choice": "with_ruc",
            "py_fiscal_decision_id": f"auto-{suffix}",
        })
        document = self.env["fiscal.document"].sudo().create({
            "name": f"Auto fiscal document {suffix}",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_sifen",
            "state": "ready",
            "customer_name": "POS Customer",
            "issue_datetime": fields.Datetime.now(),
            "amount_total": 100,
        })
        return order, document

    def test_enqueue_is_idempotent_and_performs_no_submission(self):
        order, document = self._records("queue-once")
        model = self.env["py.pos.fiscal.submission.job"]

        first = model.enqueue(order=order, document=document)
        second = model.enqueue(order=order, document=document)

        self.assertEqual(first, second)
        self.assertEqual(first.state, "queued")
        self.assertEqual(first.attempt_count, 0)
        self.assertFalse(first.transmission_id)
        self.assertFalse(document.transmission_ids)

    def test_disabled_configuration_does_not_queue(self):
        order, document = self._records("disabled")
        self.config.py_fiscal_auto_submit_enabled = False

        job = self.env["py.pos.fiscal.submission.job"].enqueue(
            order=order, document=document
        )

        self.assertFalse(job)
        self.assertFalse(document.transmission_ids)

    def test_claim_is_single_shot_and_never_requeues(self):
        order, document = self._records("claim-once")
        job = self.env["py.pos.fiscal.submission.job"].enqueue(
            order=order, document=document
        )

        self.assertTrue(job._claim_once())
        self.assertEqual(job.state, "processing")
        self.assertEqual(job.attempt_count, 1)
        self.assertFalse(job._claim_once())

    def test_execute_reuses_operator_service_and_disables_retry(self):
        order, document = self._records("execute-once")
        job = self.env["py.pos.fiscal.submission.job"].enqueue(
            order=order, document=document
        )
        transmission = self.env["fiscal.transmission"].sudo().create({
            "document_id": document.id,
            "transmission_type": "submit",
            "state": "accepted",
            "retry_state": "scheduled",
            "max_retry_count": 3,
            "next_retry_at": fields.Datetime.now(),
        })
        # The transmission represents the mocked service result, not pre-existing history.
        job.write({"state": "processing", "attempt_count": 1})
        service = Mock()
        service.submit.return_value = {
            "transmission_id": transmission.id,
            "submission_status": "accepted",
            "authority_code": "0260",
            "authority_message": "Accepted",
            "authority_protocol": "123",
            "ambiguous": False,
        }

        result = job._execute_once(operator_service=service)

        service.submit.assert_called_once_with(document=document)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(job.state, "completed")
        self.assertEqual(job.attempt_count, 1)
        self.assertEqual(job.transmission_id, transmission)
        self.assertEqual(transmission.retry_state, "not_retryable")
        self.assertEqual(transmission.max_retry_count, 0)
        self.assertFalse(transmission.next_retry_at)
        status = self.env["py.pos.fiscal.submission.job"].status_for_pos(order=order)
        self.assertEqual(status["status"], "accepted")
        self.assertEqual(status["authority_code"], "0260")
        self.assertEqual(status["authority_protocol"], "123")

    def test_pos_status_distinguishes_rejection_and_recovery(self):
        order, document = self._records("status-outcomes")
        job = self.env["py.pos.fiscal.submission.job"].enqueue(
            order=order, document=document
        )
        job.write({
            "state": "completed",
            "attempt_count": 1,
            "submission_status": "rejected",
            "authority_code": "1306",
            "authority_message": "Receiver not found",
        })

        rejected = self.env["py.pos.fiscal.submission.job"].status_for_pos(order=order)
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["authority_code"], "1306")

        job.write({"ambiguous": True})
        recovery = self.env["py.pos.fiscal.submission.job"].status_for_pos(order=order)
        self.assertEqual(recovery["status"], "recovery_required")
        self.assertTrue(recovery["ambiguous"])

    def test_pos_status_is_read_only_and_never_submits(self):
        order, document = self._records("status-read-only")
        job = self.env["py.pos.fiscal.submission.job"].enqueue(
            order=order, document=document
        )

        status = self.env["py.pos.fiscal.submission.job"].status_for_pos(order=order)

        self.assertEqual(status["status"], "queued")
        self.assertEqual(job.state, "queued")
        self.assertEqual(job.attempt_count, 0)
        self.assertFalse(document.transmission_ids)

    def test_pos_status_projects_email_delivery_without_fiscal_side_effects(self):
        order, document = self._records("delivery-status")
        document.write({
            "customer_email": "receiver@example.test",
            "py_cdc": "01" + "0" * 42,
        })
        job = self.env["py.pos.fiscal.submission.job"].enqueue(
            order=order, document=document
        )
        job.write({
            "state": "completed",
            "attempt_count": 1,
            "submission_status": "accepted",
            "authority_code": "0260",
        })
        delivery = self.env["py.fiscal.email.delivery"].sudo().create({
            "document_id": document.id,
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "cdc": document.py_cdc,
            "recipient_email": document.customer_email,
            "mode": "automatic",
            "requested_at": fields.Datetime.now(),
        })

        status = self.env["py.pos.fiscal.submission.job"].status_for_pos(order=order)

        self.assertEqual(status["status"], "accepted")
        self.assertTrue(status["delivery_ready"])
        self.assertEqual(status["email_status"], "queued")
        self.assertEqual(delivery.preparation_status, "queued")
        self.assertFalse(document.transmission_ids)

    def test_unclaimed_job_cannot_execute(self):
        order, document = self._records("not-claimed")
        job = self.env["py.pos.fiscal.submission.job"].enqueue(
            order=order, document=document
        )
        with self.assertRaisesRegex(ValidationError, "not executable"):
            job._execute_once(operator_service=Mock())

    def test_configuration_requires_authorized_operator(self):
        with self.assertRaisesRegex(ValidationError, "authorized operator"):
            self.config.write({"py_fiscal_auto_submit_user_id": False})
