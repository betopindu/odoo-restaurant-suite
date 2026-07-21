import json
from datetime import datetime, timedelta
from unittest.mock import patch

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


class TestPySifenRetryRunner(TransactionCase):
    NOW = datetime(2026, 7, 5, 12, 0, 0)
    CDC = "01444444017001001001452822017012515873260988"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN Retry Runner Tenant",
            "code": "sifen-retry-runner",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "SIFEN Retry Runner Document",
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
        self.execution_service = PySifenRetryExecutionService(
            self.env,
            retry_scheduler_service=scheduler,
            transmission_persistence_service=persistence,
            now_provider=lambda: self.NOW,
        )
        self.runner = self.env["py.sifen.retry.runner"]

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

    def _retryable_metadata(self):
        return json.dumps({
            "pipeline_failed_stage": "test_submission",
            "retryable": True,
            "retry_category": "connection_failure",
            "service": "py_sifen_transmission_persistence",
            "submission_status": "failed_retryable",
        }, sort_keys=True)

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

    def _run(self, **overrides):
        values = {
            "limit": 10,
            "retry_execution_service": self.execution_service,
            "payload": {"payload": "fixture"},
            "certificate_bytes": b"certificate-secret-fixture",
            "private_key_bytes": b"private-key-secret-fixture",
            "private_key_password": "password-secret-fixture",
            "signing_timestamp": self.NOW,
            "endpoint_url": "https://sifen-test.example.test/de",
        }
        values.update(overrides)
        return self.runner.run_sifen_retries(**values)

    def _create_retry_attachments(self):
        self.env["fiscal.attachment"].sudo().create_json_payload_attachment(
            self.document,
            "paraguay_payload_json",
            "runner-retry-payload.json",
            {"payload": "stored-runner-fixture"},
        )
        self.env["fiscal.attachment"].sudo().create({
            "name": "runner-retry-signed.xml",
            "document_id": self.document.id,
            "attachment_type": "paraguay_xml_signed",
            "mimetype": "application/xml",
            "filename": "runner-retry-signed.xml",
            "is_sensitive": True,
            "metadata_json": json.dumps({
                "signing_time": "2026-07-05T11:30:00",
            }),
        })

    def test_runner_executes_due_retries(self):
        transmission = self._scheduled_transmission()

        results = self._run()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["execution_status"], "executed")
        self.assertEqual(len(self.pipeline.calls), 1)
        self.assertEqual(transmission.retry_state, "none")
        self.assertFalse(transmission.next_retry_at)

    def test_runner_reconstructs_missing_retry_inputs(self):
        self._create_retry_attachments()
        self._scheduled_transmission()

        results = self.runner.run_sifen_retries(
            limit=10,
            retry_execution_service=self.execution_service,
            certificate_bytes=b"certificate-secret-fixture",
            private_key_bytes=b"private-key-secret-fixture",
            private_key_password="password-secret-fixture",
            endpoint_url="https://sifen-test.example.test/de",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["execution_status"], "executed")
        self.assertEqual(
            self.pipeline.calls[0]["payload"],
            {"payload": "stored-runner-fixture"},
        )
        self.assertEqual(
            self.pipeline.calls[0]["signing_timestamp"],
            "2026-07-05T11:30:00",
        )

    def test_runner_respects_batch_size(self):
        first = self._scheduled_transmission(request_hash="5" * 64)
        self._scheduled_transmission(request_hash="6" * 64)

        results = self._run(limit=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_transmission_id"], first.id)
        self.assertEqual(len(self.pipeline.calls), 1)

    def test_runner_ignores_not_yet_due_retries(self):
        self._scheduled_transmission(next_retry_at=self.NOW + timedelta(seconds=60))

        results = self._run()

        self.assertEqual(results, [])
        self.assertEqual(len(self.pipeline.calls), 0)

    def test_runner_ignores_non_retryable_transmissions(self):
        self._scheduled_transmission(
            state="accepted",
            error_code="",
            retry_state="scheduled",
            next_retry_at=self.NOW - timedelta(seconds=1),
        )

        results = self._run()

        self.assertEqual(results, [])
        self.assertEqual(len(self.pipeline.calls), 0)

    def test_runner_is_idempotent(self):
        self._scheduled_transmission()

        first = self._run()
        second = self._run()

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(self.pipeline.calls), 1)

    def test_runner_does_not_log_or_persist_secret_like_data(self):
        self._scheduled_transmission()

        with patch("odoo.addons.einvoice_py.models.py_sifen_retry_runner._logger") as logger:
            self._run()

        self.assertTrue(logger.info.called)
        log_output = json.dumps(logger.info.call_args_list, default=str, sort_keys=True)
        transmissions = self.env["fiscal.transmission"].sudo().search([
            ("document_id", "=", self.document.id),
        ])
        serialized = json.dumps(transmissions.read(), default=str, sort_keys=True)

        self.assertNotIn("private-key-secret-fixture", log_output)
        self.assertNotIn("certificate-secret-fixture", log_output)
        self.assertNotIn("password-secret-fixture", log_output)
        self.assertNotIn("IdCSC", log_output)
        self.assertNotIn("private-key-secret-fixture", serialized)
        self.assertNotIn("certificate-secret-fixture", serialized)
        self.assertNotIn("password-secret-fixture", serialized)
        self.assertNotIn("IdCSC", serialized)
