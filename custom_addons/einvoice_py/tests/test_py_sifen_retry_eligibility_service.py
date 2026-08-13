import json
from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_retry_eligibility_service import (
    PySifenRetryEligibilityService,
)
from odoo.addons.einvoice_py.services.py_sifen_retry_scheduler_service import (
    PySifenRetrySchedulerService,
)


class TestPySifenRetryEligibilityService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN 0420 Retry Evidence Tenant",
            "code": "sifen-0420-retry-evidence",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": self.id(),
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Test Customer",
            "amount_total": 100,
            "idempotency_key": self.id(),
            "py_cdc": self.CDC,
            "py_cdc_dv": self.CDC[-1],
            "country_identifier": self.CDC,
            "state": "manual_review",
        })
        self.service = PySifenRetryEligibilityService(self.env)
        self.submission = self._ambiguous_submission()
        self.query = self._query(self.submission)

    def _ambiguous_submission(self, **overrides):
        values = {
            "document_id": self.document.id,
            "transmission_type": "submit",
            "state": "manual_review",
            "country_code": "PY",
            "environment": "test",
            "country_identifier": self.CDC,
            "request_hash": "a" * 64,
            "error_code": "ambiguous_submission",
            "started_at": datetime(2026, 8, 12, 12, 0, 0),
            "metadata_json": json.dumps({
                "ambiguous": True,
                "post_started": True,
                "durability_phase": "completed",
            }),
        }
        values.update(overrides)
        return self.env["fiscal.transmission"].create(values)

    def _query(self, submission, **overrides):
        values = {
            "document_id": self.document.id,
            "transmission_type": "status_query",
            "state": "manual_review",
            "country_code": "PY",
            "environment": "test",
            "country_identifier": self.CDC,
            "request_hash": "b" * 64,
            "response_hash": "c" * 64,
            "http_status": 200,
            "authority_status_code": "0420",
            "error_code": "reconciliation_not_found",
            "started_at": datetime(2026, 8, 12, 12, 10, 0),
            "metadata_json": json.dumps({
                "result_category": "not_approved",
                "original_submission_ids": [submission.id],
                "normalized_response": {
                    "authority_code": "0420",
                    "approved": False,
                    "not_found": True,
                },
            }),
        }
        values.update(overrides)
        return self.env["fiscal.transmission"].create(values)

    def test_valid_ambiguous_submission_and_later_0420_allows_manual_only(self):
        result = self.service.classify(document=self.document)

        self.assertEqual(
            result.evidence_type,
            "reconciled_not_found_manual_retry_allowed",
        )
        self.assertTrue(result.manual_retry_allowed)
        self.assertFalse(result.automatic_retry_allowed)
        self.assertEqual(result.ambiguous_submission_id, self.submission.id)
        self.assertEqual(result.reconciliation_query_id, self.query.id)
        self.assertEqual(result.cdc, self.CDC)
        self.assertFalse(PySifenRetrySchedulerService(self.env).is_retryable(self.query))

    def test_0420_without_ambiguous_submission_is_blocked(self):
        self.submission.unlink()
        self.assertFalse(
            self.service.classify(document=self.document).manual_retry_allowed
        )

    def test_0420_for_different_cdc_is_blocked(self):
        self.query.country_identifier = "0" * 44
        self.assertFalse(
            self.service.classify(document=self.document).manual_retry_allowed
        )

    def test_0420_for_different_scope_is_blocked(self):
        self.query.environment = "production"
        self.assertFalse(
            self.service.classify(document=self.document).manual_retry_allowed
        )

    def test_0420_before_ambiguous_submission_is_blocked(self):
        self.query.started_at = self.submission.started_at - timedelta(seconds=1)
        self.assertFalse(
            self.service.classify(document=self.document).manual_retry_allowed
        )

    def test_newer_0422_is_blocked(self):
        self._query(self.submission, **{
            "state": "accepted",
            "authority_status_code": "0422",
            "error_code": "",
            "metadata_json": json.dumps({
                "result_category": "approved",
                "original_submission_ids": [self.submission.id],
                "normalized_response": {
                    "authority_code": "0422",
                    "approved": True,
                    "not_found": False,
                },
            }),
        })
        self.assertFalse(
            self.service.classify(document=self.document).manual_retry_allowed
        )

    def test_newer_out_of_scope_query_is_contradictory_and_blocks(self):
        self._query(self.submission, environment="production")

        result = self.service.classify(document=self.document)

        self.assertFalse(result.manual_retry_allowed)
        self.assertEqual(result.reason, "newer_reconciliation_exists")

    def test_accepted_submit_is_blocked(self):
        self._ambiguous_submission(
            state="accepted",
            error_code="",
            response_hash="d" * 64,
            authority_status_code="0260",
        )
        self.assertFalse(
            self.service.classify(document=self.document).manual_retry_allowed
        )

    def test_newer_unresolved_submit_is_blocked(self):
        self._ambiguous_submission(
            started_at=datetime(2026, 8, 12, 12, 20, 0)
        )
        self.assertFalse(
            self.service.classify(document=self.document).manual_retry_allowed
        )

    def test_incomplete_query_evidence_is_blocked(self):
        self.query.response_hash = ""
        self.assertFalse(
            self.service.classify(document=self.document).manual_retry_allowed
        )

    def test_authorization_fails_after_new_attempt_without_mutating_history(self):
        submission_before = self.submission.read()[0]
        query_before = self.query.read()[0]
        authorization = self.service.classify(document=self.document)
        self._ambiguous_submission(
            started_at=datetime(2026, 8, 12, 12, 20, 0)
        )

        self.assertFalse(self.service.validate_authorization(
            document=self.document,
            authorization=authorization,
        ))
        self.assertEqual(self.submission.read()[0], submission_before)
        self.assertEqual(self.query.read()[0], query_before)
