import json
from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_retry_scheduler_service import (
    PySifenRetrySchedulerService,
)


class TestPySifenRetrySchedulerService(TransactionCase):
    NOW = datetime(2026, 7, 4, 12, 0, 0)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN Retry Scheduler Tenant",
            "code": "sifen-retry-scheduler",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "SIFEN Retry Scheduler Document",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Test Customer",
            "amount_total": 100,
            "idempotency_key": self.id(),
        })
        self.service = PySifenRetrySchedulerService(
            self.env,
            base_delay_seconds=60,
            max_delay_seconds=600,
            default_max_retry_count=3,
            now_provider=lambda: self.NOW,
        )

    def _metadata(
        self,
        *,
        retryable=True,
        retry_category="connection_failure",
        failed_stage="test_submission",
    ):
        return json.dumps({
            "service": "py_sifen_transmission_persistence",
            "pipeline_failed_stage": failed_stage,
            "submission_status": "failed_retryable",
            "retryable": retryable,
            "retry_category": retry_category,
        }, sort_keys=True)

    def _transmission(self, **overrides):
        values = {
            "document_id": self.document.id,
            "attempt_number": 1,
            "transmission_type": "submit",
            "state": "failed_retryable",
            "error_code": "test_submission",
            "error_message": "SIFEN test submission failed.",
            "metadata_json": self._metadata(),
            "max_retry_count": 3,
        }
        values.update(overrides)
        return self.env["fiscal.transmission"].sudo().create(values)

    def test_retryable_failure_schedules_retry(self):
        transmission = self._transmission()

        result = self.service.schedule_retry(transmission)

        self.assertEqual(result["retry_status"], "scheduled")
        self.assertEqual(transmission.retry_state, "scheduled")
        self.assertEqual(transmission.retry_count, 1)
        self.assertEqual(transmission.next_retry_at, self.NOW + timedelta(seconds=60))

    def test_permanent_failure_does_not_retry(self):
        transmission = self._transmission(
            state="failed_final",
            error_code="final_xsd_validation",
            metadata_json=self._metadata(retryable=False, retry_category=""),
        )

        result = self.service.schedule_retry(transmission)

        self.assertEqual(result["retry_status"], "not_retryable")
        self.assertEqual(transmission.retry_state, "not_retryable")
        self.assertFalse(transmission.next_retry_at)

    def test_accepted_does_not_retry(self):
        transmission = self._transmission(
            state="accepted",
            error_code="",
            metadata_json=self._metadata(retryable=False, retry_category=""),
        )

        result = self.service.schedule_retry(transmission)

        self.assertEqual(result["retry_status"], "not_retryable")
        self.assertEqual(transmission.retry_state, "not_retryable")

    def test_retry_counter_increments(self):
        transmission = self._transmission(retry_count=1)

        self.service.schedule_retry(transmission)

        self.assertEqual(transmission.retry_count, 2)

    def test_exponential_backoff_calculation(self):
        transmission = self._transmission(retry_count=2)

        self.service.schedule_retry(transmission)

        self.assertEqual(transmission.next_retry_at, self.NOW + timedelta(seconds=240))

    def test_maximum_retries_reached(self):
        transmission = self._transmission(retry_count=3, max_retry_count=3)

        result = self.service.schedule_retry(transmission)

        self.assertEqual(result["retry_status"], "exhausted")
        self.assertEqual(transmission.retry_state, "exhausted")
        self.assertEqual(transmission.retry_count, 3)
        self.assertFalse(transmission.next_retry_at)

    def test_idempotent_scheduling(self):
        transmission = self._transmission()

        first = self.service.schedule_retry(transmission)
        second = self.service.schedule_retry(transmission)

        self.assertEqual(first["retry_status"], "scheduled")
        self.assertEqual(second["retry_status"], "scheduled")
        self.assertEqual(transmission.retry_count, 1)
        self.assertEqual(transmission.next_retry_at, self.NOW + timedelta(seconds=60))

    def test_stale_scheduled_accepted_transmission_is_not_retryable(self):
        transmission = self._stale_scheduled_transmission(state="accepted")

        result = self.service.schedule_retry(transmission)

        self.assertEqual(result["retry_status"], "not_retryable")
        self.assertEqual(transmission.retry_state, "not_retryable")
        self.assertFalse(transmission.next_retry_at)

    def test_stale_scheduled_rejected_transmission_is_not_retryable(self):
        transmission = self._stale_scheduled_transmission(state="rejected")

        result = self.service.schedule_retry(transmission)

        self.assertEqual(result["retry_status"], "not_retryable")
        self.assertEqual(transmission.retry_state, "not_retryable")
        self.assertFalse(transmission.next_retry_at)

    def test_stale_scheduled_failed_final_transmission_is_not_retryable(self):
        transmission = self._stale_scheduled_transmission(state="failed_final")

        result = self.service.schedule_retry(transmission)

        self.assertEqual(result["retry_status"], "not_retryable")
        self.assertEqual(transmission.retry_state, "not_retryable")
        self.assertFalse(transmission.next_retry_at)

    def test_non_transport_retryable_failure_does_not_retry(self):
        transmission = self._transmission(
            metadata_json=self._metadata(retryable=True, retry_category="soap_fault"),
        )

        result = self.service.schedule_retry(transmission)

        self.assertEqual(result["retry_status"], "not_retryable")
        self.assertEqual(transmission.retry_state, "not_retryable")

    def test_production_submission_failure_schedules_retry(self):
        transmission = self._transmission(
            error_code="production_submission",
            error_message="SIFEN production submission failed.",
            metadata_json=self._metadata(failed_stage="production_submission"),
        )

        result = self.service.schedule_retry(transmission)

        self.assertEqual(result["retry_status"], "scheduled")
        self.assertEqual(transmission.retry_state, "scheduled")
        self.assertEqual(transmission.retry_count, 1)

    def test_production_disallowed_retry_category_is_rejected(self):
        transmission = self._transmission(
            error_code="production_submission",
            error_message="SIFEN production submission failed.",
            metadata_json=self._metadata(
                retry_category="soap_fault",
                failed_stage="production_submission",
            ),
        )

        result = self.service.schedule_retry(transmission)

        self.assertEqual(result["retry_status"], "not_retryable")
        self.assertEqual(transmission.retry_state, "not_retryable")

    def _stale_scheduled_transmission(self, *, state):
        return self._transmission(
            state=state,
            retry_state="scheduled",
            retry_count=1,
            next_retry_at=self.NOW + timedelta(seconds=60),
        )
