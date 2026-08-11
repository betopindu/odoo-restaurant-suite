import json
from datetime import datetime, timedelta

from lxml import etree

from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
    PySifenCredentialProvider,
)
from odoo.addons.einvoice_py.services.py_sifen_retry_execution_service import (
    PySifenRetryExecutionService,
)
from odoo.addons.einvoice_py.services.py_sifen_retry_scheduler_service import (
    PySifenRetrySchedulerService,
)
from odoo.addons.einvoice_py.services.py_sifen_submission_pipeline_service import (
    PySifenSubmissionPipelineService,
)
from odoo.addons.einvoice_py.services.py_sifen_transmission_persistence_service import (
    PySifenTransmissionPersistenceService,
)
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)
from odoo.addons.einvoice_py.tests.test_py_sifen_credential_provider import (
    _Registry,
)
from odoo.addons.einvoice_py.tests import (
    test_py_sifen_submission_pipeline_service as _pipeline_fixtures,
)
from odoo.addons.einvoice_py.tests.test_py_sifen_submission_pipeline_service import (
    _QrGenerationStub,
    _SigningPipelineStub,
    _XsdValidationStub,
)


class _SequencedSubmissionStub:
    def __init__(self):
        self.calls = []

    def submit_final_xml(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return {
                "outcome": "failed_retryable",
                "authority_status_code": "",
                "authority_message": "",
                "request_hash": "c" * 64,
                "response_hash": "",
                "retryable": True,
                "metadata_json": {
                    "transport_error_category": "connection_failure",
                },
            }
        return {
            "outcome": "accepted",
            "authority_status_code": "0260",
            "authority_message": "Aprobado",
            "request_hash": "c" * 64,
            "response_hash": "d" * 64,
            "retryable": False,
            "metadata_json": {},
        }


class TestPySifenProductionFlow(TransactionCase):
    CDC = _pipeline_fixtures.TestPySifenSubmissionPipelineService.CDC
    DIGEST_VALUE = _pipeline_fixtures.TestPySifenSubmissionPipelineService.DIGEST_VALUE
    NOW = datetime(2026, 7, 20, 12, 0, 0)
    RUC = "80012345"
    CERTIFICATE_SECRET = b"production-certificate-secret-fixture"
    PRIVATE_KEY_SECRET = b"production-private-key-secret-fixture"
    PASSWORD_SECRET = b"production-password-secret-fixture"
    CSC_SECRET = "production-csc-secret-fixture"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN Production Flow Tenant",
            "code": "sifen-production-flow",
            "company_id": cls.company.id,
        })

    def setUp(self):
        super().setUp()
        self.submission_sequence = self.env["ir.sequence"].create({
            "name": "SIFEN Production Flow Submission Identifier",
            "implementation": "no_gap",
            "padding": 1,
            "number_next": 1,
            "number_increment": 1,
        })
        self.adapter = self.env["fiscal.adapter.config"].create({
            "name": "SIFEN Production Flow",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "country_code": "PY",
            "adapter_code": "py",
            "environment": "production",
            "endpoint_base_url": "https://sifen-production.example.test/de",
            "timeout_seconds": 12,
            "sequence_id": self.submission_sequence.id,
        })
        self.csc = self.env["fiscal.py.csc"].create({
            "name": "SIFEN Production Flow CSC",
            "id_csc": "0001",
            "csc_value": self.CSC_SECRET,
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "environment": "production",
        })
        self.document = self.env["fiscal.document"].create({
            "name": "SIFEN Production Flow Document",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "production",
            "adapter_code": "py",
            "adapter_config_id": self.adapter.id,
            "customer_name": "Production Customer",
            "amount_total": 100,
            "idempotency_key": self.id(),
            "py_cdc": self.CDC,
            "py_cdc_dv": self.CDC[-1],
            "country_identifier": self.CDC,
            "py_issuer_ruc": self.RUC,
            "py_csc_id": self.csc.id,
        })
        self.signing_credential = self._credential("Signing")
        self.mutual_tls_credential = self._credential("Mutual TLS")
        self._bind("xml_signing", self.signing_credential)
        self._bind("mutual_tls", self.mutual_tls_credential)

    def _credential(self, name):
        return self.env["fiscal.credential"].create({
            "name": f"Production {name}",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "provider_type": "external_secret",
            "material_format": "pem_pair",
            "secret_ref": f"secret://production-flow/{name}",
            "extracted_ruc": self.RUC,
        })

    def _bind(self, role, credential):
        return self.env["fiscal.adapter.credential.binding"].create({
            "adapter_config_id": self.adapter.id,
            "credential_id": credential.id,
            "role": role,
        })

    def test_production_services_compose_through_retry_to_acceptance(self):
        registry = _Registry(material={
            "certificate_bytes": self.CERTIFICATE_SECRET,
            "private_key_bytes": self.PRIVATE_KEY_SECRET,
            "password": self.PASSWORD_SECRET,
        })
        credential_provider = PySifenCredentialProvider(
            self.env,
            provider_registry=registry,
        )

        signed_xml = _pipeline_fixtures.TestPySifenSubmissionPipelineService._signed_xml(
            self
        )
        signed_attachment = (
            _pipeline_fixtures.TestPySifenSubmissionPipelineService._signed_attachment(
                self,
                signed_xml,
            )
        )
        signing = _SigningPipelineStub(attachment_id=signed_attachment.id)
        qr = _QrGenerationStub()
        xsd = _XsdValidationStub()
        submission = _SequencedSubmissionStub()
        pipeline = PySifenSubmissionPipelineService(
            self.env,
            signing_pipeline_service=signing,
            qr_generation_service=qr,
            xsd_validation_service=xsd,
            submission_service=submission,
        )
        persistence = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=pipeline,
            credential_provider=credential_provider,
        )
        scheduler = PySifenRetrySchedulerService(
            self.env,
            base_delay_seconds=60,
            now_provider=lambda: self.NOW,
        )

        submission_kwargs = {
            "payload": {
                "cdc": self.CDC,
                "document": {"py_cdc": self.CDC},
                "payload": "fixture",
            },
            "signing_timestamp": self.NOW,
        }
        first = persistence.submit_and_persist(
            document=self.document,
            **submission_kwargs,
        )
        first_transmission = self.env["fiscal.transmission"].browse(
            first["transmission_id"]
        )

        self.assertEqual(first_transmission.state, "failed_retryable")
        self.assertEqual(first_transmission.error_code, "production_submission")
        self.assertEqual(first_transmission.environment, "production")
        self.assertEqual(len(signing.calls), 1)
        self.assertEqual(len(qr.calls), 1)
        self.assertEqual(len(xsd.calls), 1)
        self.assertEqual(len(submission.calls), 1)

        scheduler.schedule_retry(first_transmission)
        execution = PySifenRetryExecutionService(
            self.env,
            retry_scheduler_service=scheduler,
            transmission_persistence_service=persistence,
            now_provider=lambda: self.NOW + timedelta(seconds=60),
        )
        retry = execution.execute_retry(first_transmission, **submission_kwargs)
        final_transmission = self.env["fiscal.transmission"].browse(
            retry["transmission_id"]
        )

        self.assertEqual(final_transmission.state, "accepted")
        self.assertEqual(final_transmission.authority_status_code, "0260")
        self.assertEqual(retry["retry_status"], "not_retryable")
        self.assertFalse(final_transmission.next_retry_at)
        self.assertEqual(len(signing.calls), 2)
        self.assertEqual(len(qr.calls), 2)
        self.assertEqual(len(xsd.calls), 2)
        self.assertEqual(len(submission.calls), 2)
        self.assertEqual(
            registry.credentials,
            [self.signing_credential, self.signing_credential],
        )

        for call in signing.calls:
            self.assertEqual(call["certificate_bytes"], self.CERTIFICATE_SECRET)
            self.assertEqual(call["private_key_bytes"], self.PRIVATE_KEY_SECRET)
            self.assertEqual(call["private_key_password"], self.PASSWORD_SECRET)

        for call in submission.calls:
            self.assertEqual(
                call["endpoint_url"],
                "https://sifen-production.example.test/de",
            )
            root = etree.fromstring(call["final_xml_bytes"])
            self.assertEqual(
                len(root.findall(f"{{{PyUnsignedXmlBuilder.SIFEN_NS}}}gCamFuFD")),
                1,
            )

        serialized = json.dumps({
            "first_result": first["result"],
            "retry_result": retry,
            "transmission": final_transmission.read()[0],
        }, default=str, sort_keys=True)
        for secret in (
            self.CERTIFICATE_SECRET.decode(),
            self.PRIVATE_KEY_SECRET.decode(),
            self.PASSWORD_SECRET.decode(),
            self.CSC_SECRET,
        ):
            self.assertNotIn(secret, serialized)
        self.assertNotIn("<rDE", serialized)
