import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from psycopg2 import errors
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
    PySifenCredentialConfigurationError,
)
from odoo.addons.einvoice_py.services.py_sifen_transmission_persistence_service import (
    PySifenTransmissionPersistenceService,
)
from odoo.addons.einvoice_py.services.py_sifen_durable_attempt_service import (
    PySifenDurableAttemptService,
)
from odoo.addons.einvoice_py.services.py_sifen_retry_eligibility_service import (
    PySifenRetryEligibilityService,
)
from odoo.addons.einvoice_py.services import py_sifen_durable_attempt_service


class _SubmissionPipelineStub:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def submit_test(self, **kwargs):
        self.calls.append(("test", kwargs))
        self._mark_pre_post(kwargs)
        return dict(self.result)

    def submit_production(self, **kwargs):
        self.calls.append(("production", kwargs))
        self._mark_pre_post(kwargs)
        return dict(self.result)

    def _mark_pre_post(self, kwargs):
        callback = kwargs.get("pre_post_callback")
        if callback is None or not self.result.get("request_hash"):
            return
        document = kwargs["document"]
        callback({
            "document_id": document.id,
            "tenant_id": document.tenant_id.id,
            "company_id": document.company_id.id,
            "environment": document.environment,
            "cdc": self.result["cdc"],
            "endpoint_url": kwargs.get("endpoint_url") or self.result["endpoint_url"],
            "request_hash": self.result["request_hash"],
            "payload_attachment_id": 1,
            "payload_sha256": "1" * 64,
            "unsigned_xml_attachment_id": 2,
            "unsigned_xml_sha256": "2" * 64,
            "signed_xml_attachment_id": 3,
            "signed_xml_sha256": self.result["signed_xml_sha256"],
            "qr_attachment_id": 4,
            "qr_sha256": "4" * 64,
            "qr_hash": self.result["qr_hash"],
            "rde_attachment_id": 5,
            "rde_sha256": "5" * 64,
            "signing_time": "2026-07-04T07:59:00",
            "digest_value": self.result["digest_value"],
        })


class _InspectingSubmissionPipelineStub(_SubmissionPipelineStub):
    def __init__(self, result, callback):
        super().__init__(result)
        self.callback = callback

    def submit_test(self, **kwargs):
        self.callback()
        return super().submit_test(**kwargs)


class _FakeSavepoint:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _FakeCursor:
    def __init__(self, *, locked_id=None, error=None):
        self.locked_id = locked_id
        self.error = error
        self.queries = []

    def savepoint(self):
        return _FakeSavepoint()

    def execute(self, query, params):
        self.queries.append((query, params))
        if self.error:
            raise self.error

    def fetchone(self):
        return (self.locked_id,) if self.locked_id else None


class _IndependentCursor(_FakeCursor):
    def __init__(self):
        super().__init__(locked_id=1)
        self.commit_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def commit(self):
        self.commit_count += 1


class _FakeTransmissionModel:
    def __init__(self):
        self.created = []

    def sudo(self):
        return self

    def create(self, values):
        self.created.append(values)
        return SimpleNamespace(id=991, started_at=values["started_at"])


class _FakeDocumentModel:
    def __init__(self, document):
        self.document = document

    def browse(self, document_id):
        if document_id != self.document.id:
            return SimpleNamespace(exists=lambda: False)
        return SimpleNamespace(exists=lambda: self.document)


class _FakeDurableEnvironment:
    def __init__(self, document):
        self.transmissions = _FakeTransmissionModel()
        self.documents = _FakeDocumentModel(document)

    def __getitem__(self, model_name):
        if model_name == "fiscal.transmission":
            return self.transmissions
        if model_name == "fiscal.document":
            return self.documents
        raise AssertionError(model_name)


class _CredentialProviderStub:
    def __init__(self, credentials):
        self.credentials = credentials
        self.documents = []

    def resolve(self, *, document):
        self.documents.append(document)
        return self.credentials


class TestPySifenTransmissionPersistenceService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"

    def _payload(self):
        return {"cdc": self.CDC, "document": {"py_cdc": self.CDC}, "payload": "fixture"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN Transmission Persistence Tenant",
            "code": "sifen-transmission-persistence",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "SIFEN Transmission Persistence Document",
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
        self.pipeline = _SubmissionPipelineStub(self._accepted_result())
        self.service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
        )

    def _accepted_result(self):
        return {
            "ok": True,
            "failed_stage": "",
            "error_message": "",
            "cdc": self.CDC,
            "signed_xml_sha256": "a" * 64,
            "digest_value": "digest-fixture",
            "certificate_fingerprint_sha256": "b" * 64,
            "qr_hash": "c" * 64,
            "qr_payload": (
                "https://example.test/qr?nVersion=150&Id="
                + self.CDC
                + "&IdCSC=0001&cHashQR="
                + ("c" * 64)
            ),
            "submission_status": "accepted",
            "authority_code": "0260",
            "authority_message": "Aprobado",
            "authority_receipt_ref": "12345",
            "request_hash": "d" * 64,
            "response_hash": "e" * 64,
            "endpoint_url": "https://sifen-test.example.test/de",
            "http_status": 200,
            "duration_ms": 147,
            "response_category": "authority_response",
        }

    def _submit_and_persist(self):
        return self.service.submit_and_persist(
            document=self.document,
            payload=self._payload(),
            certificate_bytes=b"certificate-secret-fixture",
            private_key_bytes=b"private-key-secret-fixture",
            private_key_password="password-secret-fixture",
            signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
            endpoint_url="https://sifen-test.example.test/de",
        )

    def _expect_runtime_error(self, operation, message):
        try:
            operation()
        except RuntimeError as error:
            self.assertIn(message, str(error))
        else:
            self.fail(f"Expected RuntimeError containing {message!r}.")

    def test_successful_persistence(self):
        result = self._submit_and_persist()
        transmission = self.env["fiscal.transmission"].browse(result["transmission_id"])

        self.assertEqual(transmission.document_id, self.document)
        self.assertEqual(transmission.country_code, "PY")
        self.assertEqual(transmission.environment, "test")
        self.assertEqual(transmission.country_identifier, self.CDC)
        self.assertEqual(transmission.state, "accepted")
        self.assertEqual(transmission.authority_status_code, "0260")
        self.assertEqual(transmission.authority_message, "Aprobado")
        self.assertEqual(transmission.request_hash, "d" * 64)
        self.assertEqual(transmission.response_hash, "e" * 64)
        self.assertEqual(transmission.endpoint_url, "https://sifen-test.example.test/de")
        self.assertEqual(transmission.http_status, 200)
        self.assertEqual(transmission.duration_ms, 147)
        self.assertEqual(transmission.signed_xml_sha256, "a" * 64)
        self.assertEqual(transmission.qr_hash, "c" * 64)
        self.assertTrue(transmission.started_at)
        self.assertTrue(transmission.finished_at)
        self.assertEqual(len(self.pipeline.calls), 1)
        self.assertEqual(self.pipeline.calls[0][0], "test")
        metadata = json.loads(transmission.metadata_json)
        self.assertEqual(metadata["durability_phase"], "completed")
        self.assertTrue(metadata["post_started"])
        self.assertEqual(metadata["payload_attachment_id"], 1)
        self.assertEqual(metadata["signed_xml_attachment_id"], 3)
        self.assertEqual(metadata["rde_attachment_id"], 5)
        self.assertEqual(metadata["authority_receipt_ref"], "12345")
        self.assertEqual(self.document.state, "accepted")
        self.assertEqual(self.document.authority_status, "0260")
        self.assertEqual(self.document.authority_receipt_ref, "12345")
        self.assertTrue(self.document.submitted_at)
        self.assertTrue(self.document.accepted_at)
        response = self.env["fiscal.attachment"].search([
            ("transmission_id", "=", transmission.id),
            ("attachment_type", "=", "authority_response"),
        ])
        self.assertFalse(response)

    def test_production_boundary_uses_independent_cursor_and_commit(self):
        cursor = _IndependentCursor()
        fake_env = _FakeDurableEnvironment(self.document)
        service = PySifenDurableAttemptService(
            self.env,
            cursor_factory=lambda: cursor,
        )
        with patch.object(py_sifen_durable_attempt_service.module, "current_test", None), \
                patch.object(service, "_environment", return_value=fake_env), \
                patch.object(service, "_lock_document"), \
                patch.object(service, "_validate_no_active_attempt"), \
                patch.object(service, "_next_attempt_number", return_value=7):
            prepared = service.prepare(
                document=self.document,
                endpoint_url="https://sifen-test.example.test/de",
            )

        self.assertEqual(prepared.transmission_id, 991)
        self.assertTrue(prepared.started_at)
        self.assertEqual(cursor.commit_count, 1)
        self.assertEqual(fake_env.transmissions.created[0]["state"], "pending")
        self.assertEqual(fake_env.transmissions.created[0]["attempt_number"], 7)

    def test_caller_does_not_reload_independently_committed_attempt(self):
        class DurableBoundaryStub:
            def __init__(self, started_at):
                self.started_at = started_at
                self.prepared_id = 991
                self.marked_ids = []
                self.finalized_ids = []

            def prepare(self, **kwargs):
                from odoo.addons.einvoice_py.services.py_sifen_durable_attempt_service import (
                    PySifenPreparedAttempt,
                )
                return PySifenPreparedAttempt(self.prepared_id, self.started_at)

            def mark_post_started(self, *, transmission_id, evidence):
                self.marked_ids.append(transmission_id)

            def finalize(
                self,
                *,
                transmission_id,
                values,
                result_metadata,
            ):
                self.finalized_ids.append(transmission_id)

        boundary = DurableBoundaryStub(datetime(2026, 7, 4, 11, 58, 0))
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            durable_attempt_service=boundary,
        )
        transmission_model = self.env["fiscal.transmission"].sudo()
        original_browse = type(transmission_model).browse

        def invisible_durable_row(recordset, ids=()):
            if ids == boundary.prepared_id:
                return original_browse(recordset, [])
            return original_browse(recordset, ids)

        with patch.object(type(transmission_model), "browse", invisible_durable_row):
            persisted = service.submit_and_persist(
                document=self.document,
                payload=self._payload(),
                certificate_bytes=b"certificate-secret-fixture",
                private_key_bytes=b"private-key-secret-fixture",
                private_key_password="password-secret-fixture",
                signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
                endpoint_url="https://sifen-test.example.test/de",
            )

        self.assertEqual(persisted["transmission_id"], boundary.prepared_id)
        self.assertEqual(boundary.marked_ids, [boundary.prepared_id])
        self.assertEqual(boundary.finalized_ids, [boundary.prepared_id])
        self.assertEqual(len(self.pipeline.calls), 1)
        self.assertEqual(self.document.submitted_at, boundary.started_at)

    def test_failure_before_durable_prepare_creates_no_attempt(self):
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            failure_injector=lambda point: (
                (_ for _ in ()).throw(RuntimeError("before durable"))
                if point == "before_durable_prepare"
                else None
            ),
        )
        self._expect_runtime_error(lambda: service.submit_and_persist(
                document=self.document,
                payload=self._payload(),
                signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
                endpoint_url="https://sifen-test.example.test/de",
            ), "before durable")
        self.assertFalse(self.document.transmission_ids)
        self.assertEqual(self.pipeline.calls, [])

    def test_failure_after_durable_prepare_leaves_pending_attempt(self):
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            failure_injector=lambda point: (
                (_ for _ in ()).throw(RuntimeError("after durable"))
                if point == "after_durable_prepare"
                else None
            ),
        )
        self._expect_runtime_error(lambda: service.submit_and_persist(
                document=self.document,
                payload=self._payload(),
                signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
                endpoint_url="https://sifen-test.example.test/de",
            ), "after durable")
        attempt = self.document.transmission_ids
        self.assertEqual(attempt.state, "pending")
        self.assertEqual(json.loads(attempt.metadata_json)["durability_phase"], "prepared")
        self.assertEqual(
            PySifenDurableAttemptService(self.env).recovery_status(attempt),
            "prepared_not_posted",
        )
        self.assertEqual(self.pipeline.calls, [])

    def test_failure_after_pre_post_boundary_leaves_ambiguous_attempt(self):
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            failure_injector=lambda point: (
                (_ for _ in ()).throw(RuntimeError("before transport"))
                if point == "after_durable_post_started"
                else None
            ),
        )
        self._expect_runtime_error(lambda: service.submit_and_persist(
                document=self.document,
                payload=self._payload(),
                signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
                endpoint_url="https://sifen-test.example.test/de",
            ), "before transport")
        attempt = self.document.transmission_ids
        metadata = json.loads(attempt.metadata_json)
        self.assertEqual(attempt.state, "sent")
        self.assertEqual(attempt.request_hash, "d" * 64)
        self.assertEqual(attempt.error_code, "ambiguous_submission")
        self.assertTrue(metadata["post_started"])
        self.assertEqual(metadata["durability_phase"], "post_started")
        self.assertEqual(
            PySifenDurableAttemptService(self.env).recovery_status(attempt),
            "outcome_unknown",
        )

    def test_failure_after_http_result_keeps_post_started_attempt(self):
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            failure_injector=lambda point: (
                (_ for _ in ()).throw(RuntimeError("after response"))
                if point == "after_pipeline_result"
                else None
            ),
        )
        self._expect_runtime_error(lambda: service.submit_and_persist(
                document=self.document,
                payload=self._payload(),
                signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
                endpoint_url="https://sifen-test.example.test/de",
            ), "after response")
        attempt = self.document.transmission_ids
        self.assertEqual(attempt.state, "sent")
        self.assertEqual(attempt.request_hash, "d" * 64)
        self.assertFalse(attempt.response_hash)

    def test_failure_after_durable_outcome_keeps_terminal_attempt(self):
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            failure_injector=lambda point: (
                (_ for _ in ()).throw(RuntimeError("after final evidence"))
                if point == "after_durable_finalize"
                else None
            ),
        )
        self._expect_runtime_error(lambda: service.submit_and_persist(
                document=self.document,
                payload=self._payload(),
                signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
                endpoint_url="https://sifen-test.example.test/de",
            ), "after final evidence")
        attempt = self.document.transmission_ids
        self.assertEqual(attempt.state, "accepted")
        self.assertEqual(attempt.response_hash, "e" * 64)
        self.assertEqual(json.loads(attempt.metadata_json)["durability_phase"], "completed")

    def test_unresolved_durable_attempt_blocks_resubmission(self):
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            failure_injector=lambda point: (
                (_ for _ in ()).throw(RuntimeError("after durable"))
                if point == "after_durable_prepare"
                else None
            ),
        )
        self._expect_runtime_error(lambda: service.submit_and_persist(
                document=self.document,
                payload=self._payload(),
                signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
                endpoint_url="https://sifen-test.example.test/de",
            ), "after durable")
        attempt = self.env["fiscal.transmission"].search([
            ("document_id", "=", self.document.id),
        ])
        self.assertEqual(attempt.state, "pending")
        self.assertEqual(attempt.country_identifier, self.CDC)
        self.assertEqual(attempt.country_code, "PY")
        with self.assertRaisesRegex(ValidationError, "unresolved|ambiguous"):
            self._submit_and_persist()

    def test_operator_can_abandon_only_proven_pre_post_attempt(self):
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            failure_injector=lambda point: (
                (_ for _ in ()).throw(RuntimeError("after durable"))
                if point == "after_durable_prepare"
                else None
            ),
        )
        self._expect_runtime_error(lambda: service.submit_and_persist(
            document=self.document,
            payload=self._payload(),
            signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
            endpoint_url="https://sifen-test.example.test/de",
        ), "after durable")
        prepared = self.document.transmission_ids
        PySifenDurableAttemptService(self.env).abandon_prepared_not_posted(prepared)
        prepared.invalidate_recordset()
        self.assertEqual(prepared.state, "failed_final")
        self.assertEqual(prepared.error_code, "pre_post_not_attempted")
        self.assertEqual(
            json.loads(prepared.metadata_json)["resolution_status"],
            "post_not_started",
        )
        completed = self._submit_and_persist()
        second = self.env["fiscal.transmission"].browse(completed["transmission_id"])
        self.assertEqual(second.attempt_number, prepared.attempt_number + 1)

    def test_post_started_attempt_cannot_be_abandoned_as_not_posted(self):
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            failure_injector=lambda point: (
                (_ for _ in ()).throw(RuntimeError("post boundary"))
                if point == "after_durable_post_started"
                else None
            ),
        )
        self._expect_runtime_error(lambda: service.submit_and_persist(
            document=self.document,
            payload=self._payload(),
            signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
            endpoint_url="https://sifen-test.example.test/de",
        ), "post boundary")
        started = self.document.transmission_ids

        with self.assertRaisesRegex(ValidationError, "proven not posted"):
            PySifenDurableAttemptService(self.env).abandon_prepared_not_posted(
                started
            )

        self.assertEqual(started.state, "sent")
        self.assertEqual(started.error_code, "ambiguous_submission")

    def test_ambiguous_transport_finalizes_same_attempt_for_reconciliation(self):
        self.pipeline.result = dict(self._accepted_result(), **{
            "ok": False,
            "failed_stage": "test_submission",
            "submission_status": "",
            "authority_code": "",
            "authority_message": "",
            "response_hash": "",
            "ambiguous": True,
            "retryable": False,
        })
        persisted = self._submit_and_persist()
        attempt = self.env["fiscal.transmission"].browse(persisted["transmission_id"])
        self.assertEqual(attempt.state, "manual_review")
        self.assertEqual(attempt.error_code, "ambiguous_submission")
        self.assertTrue(json.loads(attempt.metadata_json)["ambiguous"])

    def test_reconciled_0420_authorization_reaches_same_durable_path(self):
        self.document.with_context(
            einvoice_skip_fiscal_document_lock=True
        ).write({"state": "manual_review"})
        ambiguous = self.env["fiscal.transmission"].create({
            "document_id": self.document.id,
            "transmission_type": "submit",
            "state": "manual_review",
            "country_code": "PY",
            "environment": "test",
            "country_identifier": self.CDC,
            "request_hash": "1" * 64,
            "error_code": "ambiguous_submission",
            "started_at": datetime(2026, 7, 4, 10, 0, 0),
            "metadata_json": json.dumps({
                "ambiguous": True,
                "post_started": True,
            }),
        })
        query = self.env["fiscal.transmission"].create({
            "document_id": self.document.id,
            "transmission_type": "status_query",
            "state": "manual_review",
            "country_code": "PY",
            "environment": "test",
            "country_identifier": self.CDC,
            "request_hash": "2" * 64,
            "response_hash": "3" * 64,
            "http_status": 200,
            "authority_status_code": "0420",
            "error_code": "reconciliation_not_found",
            "started_at": datetime(2026, 7, 4, 10, 10, 0),
            "metadata_json": json.dumps({
                "result_category": "not_approved",
                "original_submission_ids": [ambiguous.id],
                "normalized_response": {
                    "authority_code": "0420",
                    "approved": False,
                    "not_found": True,
                },
            }),
        })
        authorization = PySifenRetryEligibilityService(self.env).classify(
            document=self.document
        )

        result = self.service.submit_and_persist(
            document=self.document,
            payload=self._payload(),
            certificate_bytes=b"certificate-secret-fixture",
            private_key_bytes=b"private-key-secret-fixture",
            private_key_password="password-secret-fixture",
            signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
            endpoint_url="https://sifen-test.example.test/de",
            manual_retry_authorization=authorization,
        )

        retry = self.env["fiscal.transmission"].browse(result["transmission_id"])
        metadata = json.loads(retry.metadata_json)
        self.assertEqual(retry.state, "accepted")
        self.assertEqual(metadata["manual_retry_evidence_type"], authorization.evidence_type)
        self.assertEqual(metadata["reconciled_submission_id"], ambiguous.id)
        self.assertEqual(metadata["reconciliation_query_id"], query.id)
        self.assertEqual(ambiguous.state, "manual_review")
        self.assertEqual(query.error_code, "reconciliation_not_found")

    def test_attempt_numbers_remain_monotonic_across_explicit_rejections(self):
        self.pipeline.result = dict(self._accepted_result(), **{
            "ok": False,
            "failed_stage": "test_submission",
            "submission_status": "rejected",
            "authority_code": "1300",
            "authority_message": "Explicit fixture rejection",
        })
        first = self._submit_and_persist()
        second = self._submit_and_persist()
        attempts = self.env["fiscal.transmission"].browse([
            first["transmission_id"], second["transmission_id"]
        ]).sorted("attempt_number")
        self.assertEqual(attempts.mapped("attempt_number"), [1, 2])

    def test_unresolved_attempt_from_another_tenant_does_not_cross_scope(self):
        other_tenant = self.env["fiscal.tenant"].create({
            "name": "Other durable boundary tenant",
            "code": f"other-{self.id()}",
            "company_id": self.env.company.id,
        })
        other_document = self.env["fiscal.document"].create({
            "name": "Other tenant same CDC",
            "tenant_id": other_tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Other tenant customer",
            "amount_total": 100,
            "idempotency_key": f"other-{self.id()}",
            "py_cdc": self.CDC,
            "py_cdc_dv": self.CDC[-1],
            "country_identifier": self.CDC,
        })
        self.env["fiscal.transmission"].create({
            "document_id": other_document.id,
            "transmission_type": "submit",
            "state": "pending",
            "country_code": "PY",
            "environment": "test",
            "country_identifier": self.CDC,
            "metadata_json": json.dumps({
                "durability_phase": "prepared",
                "post_started": False,
            }),
        })

        persisted = self._submit_and_persist()

        transmission = self.env["fiscal.transmission"].browse(
            persisted["transmission_id"]
        )
        self.assertEqual(transmission.document_id, self.document)
        self.assertEqual(transmission.state, "accepted")

    def test_pki_incident_is_manual_only_and_response_artifact_is_redacted(self):
        self.pipeline.result = dict(self._accepted_result(), **{
            "ok": False,
            "failed_stage": "test_submission",
            "error_message": "SIFEN test submission was not accepted.",
            "submission_status": "rejected",
            "authority_code": "0100",
            "authority_message": "Error Inesperado(PKI).",
        })

        persisted = self._submit_and_persist()
        transmission = self.env["fiscal.transmission"].browse(persisted["transmission_id"])
        metadata = json.loads(transmission.metadata_json)
        self.assertEqual(transmission.state, "rejected")
        self.assertFalse(metadata["ambiguous"])
        self.assertEqual(metadata["authority_incident_type"], "transient_authority_incident")
        self.assertTrue(metadata["manual_retry_allowed"])
        self.assertFalse(metadata["automatic_retry_allowed"])
        content = transmission.metadata_json + transmission.error_message
        for secret in ("private-key-secret-fixture", "password-secret-fixture", "certificate-secret-fixture", "<rDE"):
            self.assertNotIn(secret, content)

    def test_unsafe_endpoint_is_not_persisted(self):
        self.pipeline.result["endpoint_url"] = "https://user:secret@example.test/de?token=secret"
        persisted = self._submit_and_persist()
        transmission = self.env["fiscal.transmission"].browse(persisted["transmission_id"])
        self.assertFalse(transmission.endpoint_url)

    def test_legacy_result_without_observability_fields_remains_supported(self):
        result = self._accepted_result()
        for key in ("endpoint_url", "http_status", "duration_ms", "response_category"):
            result.pop(key)

        transmission = self.service.persist_result(
            document=self.document,
            result=result,
        )

        self.assertEqual(transmission.state, "accepted")
        self.assertFalse(transmission.endpoint_url)
        self.assertEqual(transmission.http_status, 0)
        self.assertEqual(transmission.duration_ms, 0)

    def test_pending_transmission_and_retry_payload_exist_before_pipeline(self):
        observed = {}

        def inspect_pre_post_state():
            transmission = self.env["fiscal.transmission"].search([
                ("document_id", "=", self.document.id),
            ])
            payload_attachment = self.env["fiscal.attachment"].search([
                ("document_id", "=", self.document.id),
                ("attachment_type", "=", "paraguay_payload_json"),
            ])
            observed.update({
                "transmission_state": transmission.state,
                "document_state": self.document.state,
                "payload_count": len(payload_attachment),
            })

        pipeline = _InspectingSubmissionPipelineStub(
            self._accepted_result(),
            inspect_pre_post_state,
        )
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=pipeline,
        )

        service.submit_and_persist(
            document=self.document,
            payload=self._payload(),
            certificate_bytes=b"certificate-secret-fixture",
            private_key_bytes=b"private-key-secret-fixture",
            private_key_password="password-secret-fixture",
            signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
            endpoint_url="https://sifen-test.example.test/de",
        )

        self.assertEqual(observed, {
            "transmission_state": "pending",
            "document_state": "draft",
            "payload_count": 1,
        })

    def test_resolves_credentials_when_no_credential_inputs_are_supplied(self):
        credentials = object()
        provider = _CredentialProviderStub(credentials)
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            credential_provider=provider,
        )

        service.submit_and_persist(
            document=self.document,
            payload=self._payload(),
            signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
        )

        self.assertEqual(provider.documents, [self.document])
        self.assertEqual(len(self.pipeline.calls), 1)
        self.assertEqual(self.pipeline.calls[0][0], "test")
        self.assertIs(self.pipeline.calls[0][1]["credentials"], credentials)

    def test_credential_provider_failure_prevents_submission_and_persistence(self):
        class _FailingCredentialProvider:
            def resolve(self, *, document):
                raise PySifenCredentialConfigurationError(
                    "Paraguay SIFEN credentials are not configured."
                )

        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            credential_provider=_FailingCredentialProvider(),
        )

        with self.assertRaises(PySifenCredentialConfigurationError):
            service.submit_and_persist(
                document=self.document,
                payload=self._payload(),
                signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
            )

        self.assertEqual(self.pipeline.calls, [])
        self.assertFalse(self.env["fiscal.transmission"].search([
            ("document_id", "=", self.document.id),
        ]))

    def test_supplied_runtime_credentials_bypass_resolution(self):
        credentials = object()
        provider = _CredentialProviderStub(object())
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            credential_provider=provider,
        )

        service.submit_and_persist(
            document=self.document,
            payload=self._payload(),
            signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
            credentials=credentials,
        )

        self.assertEqual(provider.documents, [])
        self.assertIs(self.pipeline.calls[0][1]["credentials"], credentials)

    def test_explicit_credential_inputs_bypass_resolution(self):
        provider = _CredentialProviderStub(object())
        service = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=self.pipeline,
            credential_provider=provider,
        )

        service.submit_and_persist(
            document=self.document,
            payload=self._payload(),
            certificate_bytes=b"certificate-secret-fixture",
            private_key_bytes=b"private-key-secret-fixture",
            private_key_password="password-secret-fixture",
            signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
            endpoint_url="https://sifen-test.example.test/de",
        )

        self.assertEqual(provider.documents, [])
        self.assertNotIn("credentials", self.pipeline.calls[0][1])

    def test_accepted_document_cannot_be_submitted_again(self):
        self._submit_and_persist()

        with self.assertRaisesRegex(ValidationError, "accepted fiscal document"):
            self._submit_and_persist()

        transmissions = self.env["fiscal.transmission"].search([
            ("document_id", "=", self.document.id),
        ])

        self.assertEqual(len(transmissions), 1)
        self.assertEqual(len(self.pipeline.calls), 1)

    def test_accepted_transmission_prevents_submission(self):
        self.service.persist_result(
            document=self.document,
            result=self._accepted_result(),
        )

        with self.assertRaisesRegex(ValidationError, "accepted transmission"):
            self._submit_and_persist()

        self.assertEqual(self.pipeline.calls, [])

    def test_concurrent_submission_lock_is_safe_and_uses_nowait(self):
        cursor = _FakeCursor(locked_id=self.document.id)
        service = PySifenDurableAttemptService(self.env)

        service._lock_document(cursor, self.document.id)

        self.assertIn("FOR UPDATE NOWAIT", cursor.queries[0][0])
        self.assertEqual(cursor.queries[0][1], [self.document.id])

        locked_cursor = _FakeCursor(error=errors.LockNotAvailable())
        with self.assertRaisesRegex(ValidationError, "already in progress"):
            service._lock_document(locked_cursor, self.document.id)

    def test_persistence_after_submission_failure(self):
        self.pipeline.result = dict(self._accepted_result(), **{
            "ok": False,
            "failed_stage": "test_submission",
            "error_message": "SIFEN test submission failed.",
            "submission_status": "",
            "authority_code": "",
            "authority_message": "",
            "request_hash": "",
            "response_hash": "",
        })

        result = self._submit_and_persist()
        transmission = self.env["fiscal.transmission"].browse(result["transmission_id"])

        self.assertEqual(transmission.state, "failed_retryable")
        self.assertEqual(transmission.error_code, "test_submission")
        self.assertEqual(transmission.error_message, "SIFEN test submission failed.")
        self.assertEqual(transmission.signed_xml_sha256, "a" * 64)
        self.assertEqual(transmission.qr_hash, "c" * 64)

    def test_no_secret_persistence(self):
        self.pipeline.result["authority_message"] = "Aprobado"

        result = self._submit_and_persist()
        transmission = self.env["fiscal.transmission"].browse(result["transmission_id"])
        serialized = json.dumps(transmission.read()[0], default=str, sort_keys=True)
        qr_payload = self.pipeline.result["qr_payload"]

        self.assertNotIn("private-key-secret-fixture", serialized)
        self.assertNotIn("certificate-secret-fixture", serialized)
        self.assertNotIn("password-secret-fixture", serialized)
        self.assertNotIn("IdCSC", serialized)
        self.assertNotIn(qr_payload, serialized)
        self.assertEqual(transmission.qr_hash, "c" * 64)
        self.assertNotIn("<soap", serialized.lower())
        self.assertNotIn("<rde", serialized.lower())

    def test_production_persistence(self):
        self.document.environment = "production"

        result = self._submit_and_persist()
        transmission = self.env["fiscal.transmission"].browse(result["transmission_id"])

        self.assertEqual(transmission.environment, "production")
        self.assertEqual(transmission.state, "accepted")
        self.assertEqual(transmission.request_hash, "d" * 64)
        self.assertEqual(transmission.response_hash, "e" * 64)
        self.assertEqual(self.pipeline.calls[0][0], "production")
        self.assertEqual(len(self.pipeline.calls), 1)

    def test_production_idempotency(self):
        self.document.environment = "production"

        first = self.service.persist_result(
            document=self.document,
            result=self._accepted_result(),
        )
        self.pipeline.result["authority_message"] = "Aprobado nuevamente"
        second = self.service.persist_result(
            document=self.document,
            result=self.pipeline.result,
        )
        transmissions = self.env["fiscal.transmission"].search([
            ("document_id", "=", self.document.id),
        ])

        self.assertEqual(first, second)
        self.assertEqual(len(transmissions), 1)
        self.assertEqual(transmissions.authority_message, "Aprobado nuevamente")
        self.assertEqual(transmissions.attempt_number, 1)
        self.assertEqual(self.pipeline.calls, [])

    def test_production_failure_persistence(self):
        self.document.environment = "production"
        self.pipeline.result = dict(self._accepted_result(), **{
            "ok": False,
            "failed_stage": "production_submission",
            "error_message": "SIFEN production submission failed.",
            "submission_status": "",
            "authority_code": "",
            "authority_message": "",
            "request_hash": "",
            "response_hash": "",
            "retryable": True,
            "retry_category": "connection_failure",
        })

        result = self._submit_and_persist()
        transmission = self.env["fiscal.transmission"].browse(result["transmission_id"])

        self.assertEqual(transmission.state, "failed_retryable")
        self.assertEqual(transmission.error_code, "production_submission")
        self.assertEqual(
            transmission.error_message,
            "SIFEN production submission failed.",
        )
        metadata = json.loads(transmission.metadata_json)
        self.assertTrue(metadata["retryable"])
        self.assertEqual(metadata["retry_category"], "connection_failure")
        self.assertEqual(metadata["pipeline_failed_stage"], "production_submission")
        self.assertEqual(transmission.signed_xml_sha256, "a" * 64)
        self.assertEqual(transmission.qr_hash, "c" * 64)
        self.assertEqual(self.pipeline.calls[0][0], "production")

    def test_unsupported_environment_is_rejected(self):
        self.document.environment = False

        with self.assertRaisesRegex(ValidationError, "supported environment"):
            self.service.persist_result(
                document=self.document,
                result=self._accepted_result(),
            )

    def test_invalid_persistence_input(self):
        with self.assertRaisesRegex(ValidationError, "dictionary"):
            self.service.persist_result(document=self.document, result="not-a-dict")

    def test_safe_signing_diagnostic_is_in_persisted_metadata(self):
        result = self._accepted_result()
        result.update({
            "diagnostic_code": "payload_schema_not_ready",
            "diagnostic_detail": "receiver city code",
        })

        metadata = self.service._metadata_values(result)

        self.assertEqual(metadata["diagnostic_code"], "payload_schema_not_ready")
        self.assertEqual(metadata["diagnostic_detail"], "receiver city code")
