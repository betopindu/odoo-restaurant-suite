import json
from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_retry_execution_service import (
    PySifenRetryExecutionService,
)
from odoo.addons.einvoice_py.services.py_sifen_retry_scheduler_service import (
    PySifenRetrySchedulerService,
)
from odoo.addons.einvoice_py.services.py_sifen_transmission_persistence_service import (
    PySifenTransmissionPersistenceService,
)


class _SubmissionPipelineStub:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def submit_test(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.result)


class TestPySifenRetryExecutionService(TransactionCase):
    NOW = datetime(2026, 7, 5, 12, 0, 0)
    CDC = "01444444017001001001452822017012515873260988"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN Retry Execution Tenant",
            "code": "sifen-retry-execution",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "SIFEN Retry Execution Document",
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
        })
        self.pipeline = _SubmissionPipelineStub(self._accepted_result("a"))
        persistence = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
        )
        scheduler = PySifenRetrySchedulerService(
            self.env,
            base_delay_seconds=60,
            max_delay_seconds=600,
            default_max_retry_count=3,
            now_provider=lambda: self.NOW,
        )
        self.service = PySifenRetryExecutionService(
            self.env,
            retry_scheduler_service=scheduler,
            transmission_persistence_service=persistence,
            now_provider=lambda: self.NOW,
        )

    def _accepted_result(self, hash_seed):
        return {
            "ok": True,
            "failed_stage": "",
            "error_message": "",
            "cdc": self.CDC,
            "signed_xml_sha256": "1" * 64,
            "digest_value": "digest-fixture",
            "certificate_fingerprint_sha256": "2" * 64,
            "qr_hash": "3" * 64,
            "qr_payload": "https://example.test/qr?IdCSC=0001&cHashQR=" + ("3" * 64),
            "submission_status": "accepted",
            "authority_code": "0300",
            "authority_message": "Aprobado",
            "request_hash": hash_seed * 64,
            "response_hash": "4" * 64,
        }

    def _retryable_result(self, hash_seed):
        return dict(self._accepted_result(hash_seed), **{
            "ok": False,
            "failed_stage": "test_submission",
            "error_message": "SIFEN test submission failed.",
            "submission_status": "",
            "authority_code": "",
            "authority_message": "",
            "response_hash": "",
            "retryable": True,
            "retry_category": "connection_failure",
        })

    def _permanent_result(self, hash_seed):
        return dict(self._accepted_result(hash_seed), **{
            "ok": False,
            "failed_stage": "final_xsd_validation",
            "error_message": "Final signed Paraguay XML failed local SIFEN XSD validation.",
            "submission_status": "",
            "authority_code": "",
            "authority_message": "",
            "retryable": False,
            "retry_category": "",
        })

    def _scheduled_transmission(self, **overrides):
        values = {
            "document_id": self.document.id,
            "attempt_number": 1,
            "transmission_type": "submit",
            "state": "failed_retryable",
            "error_code": "test_submission",
            "error_message": "SIFEN test submission failed.",
            "request_hash": "0" * 64,
            "metadata_json": self._retryable_metadata(),
            "retry_state": "scheduled",
            "retry_count": 1,
            "max_retry_count": 3,
            "next_retry_at": self.NOW - timedelta(seconds=1),
        }
        values.update(overrides)
        return self.env["fiscal.transmission"].sudo().create(values)

    def _retryable_metadata(self):
        return json.dumps({
            "pipeline_failed_stage": "test_submission",
            "retryable": True,
            "retry_category": "connection_failure",
            "service": "py_sifen_transmission_persistence",
            "submission_status": "failed_retryable",
        }, sort_keys=True)

    def _execute(self, transmission):
        return self.service.execute_retry(
            transmission,
            payload={"payload": "fixture"},
            certificate_bytes=b"certificate-secret-fixture",
            private_key_bytes=b"private-key-secret-fixture",
            private_key_password="password-secret-fixture",
            signing_timestamp=self.NOW,
            endpoint_url="https://sifen-test.example.test/de",
        )

    def test_successful_retry_executes_due_transmission(self):
        transmission = self._scheduled_transmission()

        result = self._execute(transmission)

        self.assertEqual(result["execution_status"], "executed")
        self.assertEqual(len(self.pipeline.calls), 1)
        result_transmission = self.env["fiscal.transmission"].browse(result["transmission_id"])
        self.assertEqual(result_transmission.state, "accepted")
        self.assertEqual(result_transmission.authority_status_code, "0300")
        self.assertEqual(transmission.retry_state, "none")
        self.assertFalse(transmission.next_retry_at)

    def test_retryable_failure_reschedules(self):
        self.pipeline.result = self._retryable_result("b")
        transmission = self._scheduled_transmission()

        result = self._execute(transmission)

        result_transmission = self.env["fiscal.transmission"].browse(result["transmission_id"])
        self.assertEqual(result["retry_status"], "scheduled")
        self.assertEqual(result_transmission.state, "failed_retryable")
        self.assertEqual(result_transmission.retry_count, 2)
        self.assertEqual(result_transmission.next_retry_at, self.NOW + timedelta(seconds=120))
        self.assertEqual(transmission.retry_state, "none")
        self.assertFalse(transmission.next_retry_at)

    def test_accepted_stops_retrying(self):
        transmission = self._scheduled_transmission()

        result = self._execute(transmission)

        result_transmission = self.env["fiscal.transmission"].browse(result["transmission_id"])
        self.assertEqual(result["retry_status"], "not_retryable")
        self.assertEqual(result_transmission.retry_state, "not_retryable")
        self.assertFalse(result_transmission.next_retry_at)

    def test_permanent_failure_stops_retrying(self):
        self.pipeline.result = self._permanent_result("c")
        transmission = self._scheduled_transmission()

        result = self._execute(transmission)

        result_transmission = self.env["fiscal.transmission"].browse(result["transmission_id"])
        self.assertEqual(result_transmission.state, "failed_final")
        self.assertEqual(result["retry_status"], "not_retryable")
        self.assertEqual(result_transmission.retry_state, "not_retryable")
        self.assertFalse(result_transmission.next_retry_at)

    def test_max_retries_reached_stops_rescheduling(self):
        self.pipeline.result = self._retryable_result("d")
        transmission = self._scheduled_transmission(retry_count=3, max_retry_count=3)

        result = self._execute(transmission)

        result_transmission = self.env["fiscal.transmission"].browse(result["transmission_id"])
        self.assertEqual(result["retry_status"], "exhausted")
        self.assertEqual(result_transmission.retry_state, "exhausted")
        self.assertEqual(result_transmission.retry_count, 3)
        self.assertFalse(result_transmission.next_retry_at)

    def test_transmission_not_yet_due_is_ignored(self):
        transmission = self._scheduled_transmission(
            next_retry_at=self.NOW + timedelta(seconds=60),
        )

        result = self._execute(transmission)

        self.assertEqual(result["execution_status"], "ignored")
        self.assertEqual(len(self.pipeline.calls), 0)
        self.assertEqual(transmission.retry_state, "scheduled")
        self.assertEqual(transmission.next_retry_at, self.NOW + timedelta(seconds=60))

    def test_stale_scheduled_accepted_transmission_is_not_executed(self):
        transmission = self._stale_scheduled_transmission(state="accepted")

        result = self._execute(transmission)

        self.assertEqual(result["execution_status"], "ignored")
        self.assertEqual(len(self.pipeline.calls), 0)
        self.assertEqual(transmission.retry_state, "not_retryable")
        self.assertFalse(transmission.next_retry_at)

    def test_stale_scheduled_rejected_transmission_is_not_executed(self):
        transmission = self._stale_scheduled_transmission(state="rejected")

        result = self._execute(transmission)

        self.assertEqual(result["execution_status"], "ignored")
        self.assertEqual(len(self.pipeline.calls), 0)
        self.assertEqual(transmission.retry_state, "not_retryable")
        self.assertFalse(transmission.next_retry_at)

    def test_stale_scheduled_failed_final_transmission_is_not_executed(self):
        transmission = self._stale_scheduled_transmission(state="failed_final")

        result = self._execute(transmission)

        self.assertEqual(result["execution_status"], "ignored")
        self.assertEqual(len(self.pipeline.calls), 0)
        self.assertEqual(transmission.retry_state, "not_retryable")
        self.assertFalse(transmission.next_retry_at)

    def test_idempotent_execution(self):
        transmission = self._scheduled_transmission()

        first = self._execute(transmission)
        second = self._execute(transmission)

        self.assertEqual(first["execution_status"], "executed")
        self.assertEqual(second["execution_status"], "ignored")
        self.assertEqual(len(self.pipeline.calls), 1)

    def test_execute_ready_selects_due_transmissions_only(self):
        due = self._scheduled_transmission(request_hash="5" * 64)
        self._scheduled_transmission(
            request_hash="6" * 64,
            next_retry_at=self.NOW + timedelta(seconds=60),
        )

        results = self.service.execute_ready(
            payload={"payload": "fixture"},
            certificate_bytes=b"certificate-secret-fixture",
            private_key_bytes=b"private-key-secret-fixture",
            private_key_password="password-secret-fixture",
            signing_timestamp=self.NOW,
            endpoint_url="https://sifen-test.example.test/de",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_transmission_id"], due.id)
        self.assertEqual(len(self.pipeline.calls), 1)

    def _stale_scheduled_transmission(self, *, state):
        return self._scheduled_transmission(
            state=state,
            retry_state="scheduled",
            next_retry_at=self.NOW - timedelta(seconds=1),
        )
