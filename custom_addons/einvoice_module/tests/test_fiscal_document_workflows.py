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

    def _create_user(self, login):
        return self.env["res.users"].with_context(no_reset_password=True).create({
            "name": login,
            "login": login,
            "email": f"{login}@example.com",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            "allowed_fiscal_tenant_ids": [(6, 0, [self.tenant.id])],
        })

    def _create_lock_policy(self, states, allow_admin_override=True):
        return self.env["fiscal.document.lock.policy"].create({
            "name": f"Policy {self._testMethodName}",
            "allow_admin_override": allow_admin_override,
            "line_ids": [
                (0, 0, {"state": state})
                for state in states
            ],
        })

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

    def test_admin_editing_locked_document_creates_manual_override_event(self):
        document = self._create_document("accepted")
        admin = self.env.ref("base.user_admin")

        document.with_user(admin).write({
            "customer_name": "Admin Override Customer",
            "customer_email": "override@example.com",
        })

        events = self.env["fiscal.event"].search([
            ("document_id", "=", document.id),
            ("event_type", "=", "manual_override"),
        ])
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.from_state, "accepted")
        self.assertEqual(event.to_state, "accepted")
        self.assertEqual(event.actor_type, "user")
        self.assertEqual(event.user_id, admin)
        self.assertEqual(event.message, "Admin override edit on locked fiscal document")

    def test_normal_user_editing_locked_document_remains_blocked(self):
        document = self._create_document("accepted", key_suffix="accepted-user")
        user = self._create_user("fiscal-normal-user")

        with self.assertRaises(ValidationError):
            document.with_user(user).write({"customer_name": "Blocked Edit"})

        events = self.env["fiscal.event"].search([
            ("document_id", "=", document.id),
            ("event_type", "=", "manual_override"),
        ])
        self.assertFalse(events)

    def test_no_tenant_policy_uses_fallback_locked_states(self):
        document = self._create_document("accepted", key_suffix="fallback-accepted")
        user = self._create_user("fallback-lock-user")

        with self.assertRaises(ValidationError):
            document.with_user(user).write({"customer_name": "Blocked Fallback"})

    def test_tenant_policy_can_lock_rejected(self):
        policy = self._create_lock_policy(["rejected"])
        self.tenant.lock_policy_id = policy
        document = self._create_document("rejected")
        user = self._create_user("rejected-lock-user")

        with self.assertRaises(ValidationError):
            document.with_user(user).write({"customer_name": "Blocked Rejected"})

    def test_tenant_policy_can_omit_manual_review(self):
        policy = self._create_lock_policy(["accepted"])
        self.tenant.lock_policy_id = policy
        document = self._create_document("manual_review", key_suffix="editable-manual")
        user = self._create_user("manual-review-edit-user")

        document.with_user(user).write({"customer_name": "Manual Review Editable"})

        self.assertEqual(document.customer_name, "Manual Review Editable")
        events = self.env["fiscal.event"].search([
            ("document_id", "=", document.id),
            ("event_type", "=", "manual_override"),
        ])
        self.assertFalse(events)

    def test_tenant_policy_can_disable_admin_override(self):
        policy = self._create_lock_policy(["accepted"], allow_admin_override=False)
        self.tenant.lock_policy_id = policy
        document = self._create_document("accepted", key_suffix="admin-disabled")
        admin = self.env.ref("base.user_admin")

        with self.assertRaises(ValidationError):
            document.with_user(admin).write({"customer_name": "Blocked Admin"})

        events = self.env["fiscal.event"].search([
            ("document_id", "=", document.id),
            ("event_type", "=", "manual_override"),
        ])
        self.assertFalse(events)

    def test_lock_bypass_context_still_allows_system_transition_writes(self):
        policy = self._create_lock_policy(["accepted"], allow_admin_override=False)
        self.tenant.lock_policy_id = policy
        document = self._create_document("accepted", key_suffix="context-bypass")
        admin = self.env.ref("base.user_admin")

        document.with_user(admin).with_context(
            einvoice_skip_fiscal_document_lock=True,
        ).write({"customer_name": "Bypass Edit"})

        self.assertEqual(document.customer_name, "Bypass Edit")
        events = self.env["fiscal.event"].search([
            ("document_id", "=", document.id),
            ("event_type", "=", "manual_override"),
        ])
        self.assertFalse(events)
