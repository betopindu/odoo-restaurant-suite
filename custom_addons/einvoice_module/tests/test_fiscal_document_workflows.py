from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestFiscalDocumentWorkflows(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "Workflow Tenant",
            "code": "workflow",
            "company_id": cls.env.company.id,
        })

    def _create_document(self, state, key_suffix=None):
        key_suffix = key_suffix or state
        return self.env["fiscal.document"].create({
            "name": f"Test {state}",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "fake",
            "customer_name": "Test Customer",
            "amount_total": 100,
            "idempotency_key": f"workflow-{key_suffix}-{self._testMethodName}",
            "state": state,
        })

    def _latest_transition_event(self, document):
        return self.env["fiscal.event"].search(
            [
                ("document_id", "=", document.id),
                ("event_type", "=", "state_transition"),
            ],
            order="occurred_at desc, id desc",
            limit=1,
        )

    def test_retry_validation_error_requeues_and_creates_user_event(self):
        document = self._create_document("validation_error")

        document.action_retry_validation_error()

        self.assertEqual(document.state, "queued")
        event = self._latest_transition_event(document)
        self.assertEqual(event.from_state, "validation_error")
        self.assertEqual(event.to_state, "queued")
        self.assertEqual(event.actor_type, "user")
        self.assertEqual(event.user_id, self.env.user)
        self.assertEqual(
            event.message,
            "Validation error resolved and document requeued",
        )

    def test_retry_manual_review_requeues(self):
        document = self._create_document("manual_review")

        document.action_retry_manual_review()

        self.assertEqual(document.state, "queued")
        event = self._latest_transition_event(document)
        self.assertEqual(event.from_state, "manual_review")
        self.assertEqual(event.to_state, "queued")
        self.assertEqual(event.actor_type, "user")
        self.assertEqual(event.message, "Manual review resolved by retry")

    def test_fail_manual_review_marks_failed_final(self):
        document = self._create_document("manual_review")

        document.action_fail_manual_review()

        self.assertEqual(document.state, "failed_final")
        event = self._latest_transition_event(document)
        self.assertEqual(event.from_state, "manual_review")
        self.assertEqual(event.to_state, "failed_final")
        self.assertEqual(event.actor_type, "user")
        self.assertEqual(event.message, "Manual review resolved as failed final")

    def test_cancel_manual_review_cancels(self):
        document = self._create_document("manual_review")

        document.action_cancel_manual_review()

        self.assertEqual(document.state, "cancelled")
        event = self._latest_transition_event(document)
        self.assertEqual(event.from_state, "manual_review")
        self.assertEqual(event.to_state, "cancelled")
        self.assertEqual(event.actor_type, "user")
        self.assertEqual(event.message, "Manual review cancelled")

    def test_manual_review_actions_rejected_outside_manual_review(self):
        actions = (
            "action_retry_manual_review",
            "action_fail_manual_review",
            "action_cancel_manual_review",
        )
        for index, action in enumerate(actions):
            document = self._create_document("queued", key_suffix=f"queued-{index}")
            with self.subTest(action=action):
                with self.assertRaises(ValidationError):
                    getattr(document, action)()
                self.assertEqual(document.state, "queued")
