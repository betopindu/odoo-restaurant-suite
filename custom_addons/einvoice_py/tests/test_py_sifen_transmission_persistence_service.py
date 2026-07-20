import json
from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

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


class TestPySifenTransmissionPersistenceService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"

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
            "authority_code": "0300",
            "authority_message": "Aprobado",
            "request_hash": "d" * 64,
            "response_hash": "e" * 64,
        }

    def _submit_and_persist(self):
        return self.service.submit_and_persist(
            document=self.document,
            payload={"payload": "fixture"},
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
        self.assertEqual(transmission.authority_status_code, "0300")
        self.assertEqual(transmission.authority_message, "Aprobado")
        self.assertEqual(transmission.request_hash, "d" * 64)
        self.assertEqual(transmission.response_hash, "e" * 64)
        self.assertEqual(transmission.signed_xml_sha256, "a" * 64)
        self.assertEqual(transmission.qr_hash, "c" * 64)
        self.assertTrue(transmission.started_at)
        self.assertTrue(transmission.finished_at)
        self.assertEqual(len(self.pipeline.calls), 1)
        self.assertEqual(self.pipeline.calls[0][0], "test")

    def test_idempotent_repeated_persistence_updates_existing_record(self):
        first = self._submit_and_persist()
        self.pipeline.result["authority_message"] = "Aprobado nuevamente"
        second = self._submit_and_persist()
        transmissions = self.env["fiscal.transmission"].search([
            ("document_id", "=", self.document.id),
        ])

        self.assertEqual(first["transmission_id"], second["transmission_id"])
        self.assertEqual(len(transmissions), 1)
        self.assertEqual(transmissions.authority_message, "Aprobado nuevamente")
        self.assertEqual(transmissions.attempt_number, 1)
        self.assertEqual(len(self.pipeline.calls), 2)

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

        first = self._submit_and_persist()
        self.pipeline.result["authority_message"] = "Aprobado nuevamente"
        second = self._submit_and_persist()
        transmissions = self.env["fiscal.transmission"].search([
            ("document_id", "=", self.document.id),
        ])

        self.assertEqual(first["transmission_id"], second["transmission_id"])
        self.assertEqual(len(transmissions), 1)
        self.assertEqual(transmissions.authority_message, "Aprobado nuevamente")
        self.assertEqual(transmissions.attempt_number, 1)
        self.assertEqual([call[0] for call in self.pipeline.calls], [
            "production",
            "production",
        ])

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
        })

        result = self._submit_and_persist()
        transmission = self.env["fiscal.transmission"].browse(result["transmission_id"])

        self.assertEqual(transmission.state, "failed_final")
        self.assertEqual(transmission.error_code, "production_submission")
        self.assertEqual(
            transmission.error_message,
            "SIFEN production submission failed.",
        )
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
