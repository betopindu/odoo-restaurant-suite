import json
from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_operator_service import (
    PySifenOperatorService,
)
from odoo.addons.einvoice_py.services.py_sifen_test_readiness_service import (
    PySifenTestReadinessService,
)


class _Ready:
    def check(self, *, document):
        return {"ready": True, "errors": []}


class _NotReady:
    def check(self, *, document):
        return {"ready": False, "errors": ["Credential scope is incomplete."]}


class _Source:
    def read_current_payload(self, *, document):
        return object(), {"document": {"cdc": document.country_identifier}}


class _Clock:
    def fresh(self, *, document, reference_instant=None):
        return "2026-08-18T10:00:00"


class _Persistence:
    def __init__(self, document):
        self.document = document
        self.calls = 0

    def submit_and_persist(self, **kwargs):
        self.calls += 1
        self.document.with_context(einvoice_skip_fiscal_document_lock=True).write({
            "state": "accepted", "authority_status": "0260", "authority_receipt_ref": "12345",
        })
        return {"transmission_id": 9001, "result": {
            "submission_status": "accepted", "authority_code": "0260",
            "authority_message": "Accepted", "authority_receipt_ref": "12345",
            "ambiguous": False, "http_status": 200, "duration_ms": 25,
        }}


class _ManualRetry:
    def __init__(self, allowed=False):
        self.allowed = allowed
        self.calls = 0

    def validate(self, **kwargs):
        if not self.allowed:
            raise ValidationError("Manual retry blocked")
        return object()

    def retry(self, **kwargs):
        self.calls += 1
        return {"transmission_id": 9002, "result": {
            "submission_status": "rejected", "authority_code": "1306",
            "authority_message": "Receiver missing", "ambiguous": False,
            "http_status": 200, "duration_ms": 20,
        }}


class _Reconciliation:
    def __init__(self):
        self.calls = 0

    def reconcile(self, **kwargs):
        self.calls += 1
        return {"resolution_status": "accepted", "query_transmission_id": 9100,
                "authority_code": "0422"}


class TestPySifenOperatorUi(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "Operator tenant", "code": "operator-ui", "company_id": cls.company.id,
        })
        cls.adapter = cls.env["fiscal.adapter.config"].create({
            "name": "Operator adapter", "tenant_id": cls.tenant.id,
            "company_id": cls.company.id, "country_code": "PY",
            "adapter_code": "py_sifen", "environment": "test",
        })
        cls.operator = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Fiscal Operator", "login": "fiscal-operator-ui",
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, [cls.env.ref("einvoice_py.group_py_fiscal_operator").id])],
            "allowed_fiscal_tenant_ids": [(6, 0, [cls.tenant.id])],
        })
        cls.regular = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Regular User", "login": "regular-ui",
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
            "allowed_fiscal_tenant_ids": [(6, 0, [cls.tenant.id])],
        })

    def _document(self, state="ready"):
        return self.env["fiscal.document"].create({
            "name": "Operator fixture", "tenant_id": self.tenant.id,
            "company_id": self.company.id, "adapter_config_id": self.adapter.id,
            "document_type": "invoice", "state": state, "country_code": "PY",
            "environment": "test", "country_identifier": "1" * 44, "py_cdc": "1" * 44,
        })

    def _service(self, document, **overrides):
        return PySifenOperatorService(
            self.env(user=self.operator),
            readiness_service=overrides.get("readiness", _Ready()),
            persistence_service=overrides.get("persistence", _Persistence(document)),
            manual_retry_service=overrides.get("manual", _ManualRetry()),
            reconciliation_service=overrides.get("reconciliation", _Reconciliation()),
            source_artifact_service=_Source(), signing_time_service=_Clock(),
        )

    def test_initial_submission_uses_existing_persistence_boundary_once(self):
        document = self._document()
        persistence = _Persistence(document)
        result = self._service(document, persistence=persistence).submit(
            document=document.with_user(self.operator)
        )
        self.assertEqual(persistence.calls, 1)
        self.assertEqual(result["authority_code"], "0260")
        self.assertEqual(document.state, "accepted")
        with self.assertRaisesRegex(ValidationError, "accepted|not eligible|Manual retry"):
            self._service(document, persistence=persistence).submit(
                document=document.with_user(self.operator)
            )
        self.assertEqual(persistence.calls, 1)

    def test_permission_is_checked_by_action_and_service(self):
        document = self._document()
        with self.assertRaisesRegex(AccessError, "authorized fiscal operator"):
            document.with_user(self.regular).action_open_py_sifen_submission()
        service = PySifenOperatorService(
            self.env(user=self.regular), readiness_service=_Ready(),
            persistence_service=_Persistence(document), manual_retry_service=_ManualRetry(),
            source_artifact_service=_Source(), signing_time_service=_Clock(),
        )
        with self.assertRaises(AccessError):
            service.submit(document=document.with_user(self.regular))

    def test_open_action_is_confirmation_only_and_has_no_transport(self):
        document = self._document().with_user(self.operator)
        action = document.action_open_py_sifen_submission()
        wizard = self.env["py.sifen.operator.wizard"].browse(action["res_id"])
        self.assertEqual(action["target"], "new")
        self.assertEqual(wizard.operation, "submit")
        self.assertEqual(len(document.transmission_ids), 0)

    def test_readiness_action_is_offline_and_reports_safe_status(self):
        document = self._document().with_user(self.operator)
        report = {"ready": True, "status": "ready", "errors": []}
        with patch.object(PySifenTestReadinessService, "check", return_value=report) as check:
            action = document.action_check_py_sifen_readiness()
        check.assert_called_once_with(document=document)
        self.assertEqual(action["params"]["type"], "success")
        self.assertEqual(len(document.transmission_ids), 0)

    def test_readiness_failure_is_closed_before_persistence(self):
        document = self._document()
        persistence = _Persistence(document)
        with self.assertRaisesRegex(ValidationError, "Credential scope"):
            self._service(document, readiness=_NotReady(), persistence=persistence).submit(
                document=document.with_user(self.operator)
            )
        self.assertEqual(persistence.calls, 0)

    def test_ambiguous_submission_exposes_only_consulta_recovery(self):
        document = self._document(state="manual_review")
        transmission = self.env["fiscal.transmission"].sudo().create({
            "document_id": document.id, "transmission_type": "submit", "state": "manual_review",
            "country_code": "PY", "environment": "test", "country_identifier": document.py_cdc,
            "error_code": "ambiguous_submission",
            "metadata_json": json.dumps({"ambiguous": True, "post_started": True}),
        })
        reconciliation = _Reconciliation()
        service = self._service(document, reconciliation=reconciliation)
        self.assertTrue(service.can_reconcile(document=document))
        result = service.reconcile(document=document.with_user(self.operator))
        self.assertEqual(result["authority_code"], "0422")
        self.assertEqual(reconciliation.calls, 1)
        self.assertEqual(transmission.state, "manual_review")

    def test_reconciliation_without_ambiguous_evidence_is_blocked(self):
        document = self._document()
        reconciliation = _Reconciliation()
        with self.assertRaisesRegex(ValidationError, "ambiguous"):
            self._service(document, reconciliation=reconciliation).reconcile(
                document=document.with_user(self.operator)
            )
        self.assertEqual(reconciliation.calls, 0)

    def test_completed_0420_does_not_offer_repeated_consulta(self):
        document = self._document(state="manual_review")
        self.env["fiscal.transmission"].sudo().create({
            "document_id": document.id, "transmission_type": "submit", "state": "manual_review",
            "country_code": "PY", "environment": "test", "country_identifier": document.py_cdc,
            "error_code": "ambiguous_submission", "metadata_json": json.dumps({"ambiguous": True}),
        })
        self.env["fiscal.transmission"].sudo().create({
            "document_id": document.id, "transmission_type": "status_query", "state": "manual_review",
            "country_code": "PY", "environment": "test", "country_identifier": document.py_cdc,
            "authority_status_code": "0420", "error_code": "reconciliation_not_found",
        })
        manual = _ManualRetry(allowed=True)
        service = self._service(document, manual=manual)
        self.assertFalse(service.can_reconcile(document=document))
        self.assertEqual(service.guidance(document=document)[0], "manual_retry_allowed")

    def test_manual_retry_path_never_uses_initial_persistence(self):
        document = self._document(state="rejected")
        self.env["fiscal.transmission"].sudo().create({
            "document_id": document.id, "transmission_type": "submit", "state": "rejected",
            "country_code": "PY", "environment": "test", "country_identifier": document.py_cdc,
        })
        manual = _ManualRetry(allowed=True)
        persistence = _Persistence(document)
        result = self._service(document, manual=manual, persistence=persistence).submit(
            document=document.with_user(self.operator)
        )
        self.assertEqual(result["operation"], "manual_retry")
        self.assertEqual(manual.calls, 1)
        self.assertEqual(persistence.calls, 0)

    def test_wizard_confirm_delegates_without_fiscal_logic(self):
        document = self._document()
        wizard = self.env["py.sifen.operator.wizard"].with_user(self.operator).create({
            "document_id": document.id, "operation": "submit", "warning": "Confirm",
        })
        safe = {"transmission_id": 42, "submission_status": "rejected",
                "authority_code": "1306", "authority_message": "Rejected",
                "ambiguous": False}
        with patch.object(PySifenOperatorService, "submit", return_value=safe) as submit:
            action = wizard.action_confirm()
        submit.assert_called_once()
        self.assertEqual(action["tag"], "display_notification")
