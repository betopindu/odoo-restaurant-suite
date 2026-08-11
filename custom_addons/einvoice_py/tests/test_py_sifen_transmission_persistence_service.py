import json
from datetime import datetime
from types import SimpleNamespace

from psycopg2 import errors
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
    PySifenCredentialConfigurationError,
)
from odoo.addons.einvoice_py.services.py_sifen_transmission_persistence_service import (
    PySifenTransmissionPersistenceService,
)


class _SubmissionPipelineStub:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def submit_test(self, **kwargs):
        self.calls.append(("test", kwargs))
        return dict(self.result)

    def submit_production(self, **kwargs):
        self.calls.append(("production", kwargs))
        return dict(self.result)


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
        self.assertEqual(len(response), 1)
        self.assertTrue(response.is_sensitive)

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
        attachment = self.env["fiscal.attachment"].search([
            ("transmission_id", "=", transmission.id),
            ("attachment_type", "=", "authority_response"),
        ])
        content = attachment.ir_attachment_id.raw.decode("utf-8")

        self.assertEqual(transmission.state, "rejected")
        self.assertFalse(metadata["ambiguous"])
        self.assertEqual(metadata["authority_incident_type"], "transient_authority_incident")
        self.assertTrue(metadata["manual_retry_allowed"])
        self.assertFalse(metadata["automatic_retry_allowed"])
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
            "document_state": "submitted",
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
        service = object.__new__(PySifenTransmissionPersistenceService)
        service.env = SimpleNamespace(cr=cursor)

        service._lock_document(SimpleNamespace(id=self.document.id))

        self.assertIn("FOR UPDATE NOWAIT", cursor.queries[0][0])
        self.assertEqual(cursor.queries[0][1], [self.document.id])

        locked_cursor = _FakeCursor(error=errors.LockNotAvailable())
        service.env = SimpleNamespace(cr=locked_cursor)
        with self.assertRaisesRegex(ValidationError, "already in progress"):
            service._lock_document(SimpleNamespace(id=self.document.id))

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
