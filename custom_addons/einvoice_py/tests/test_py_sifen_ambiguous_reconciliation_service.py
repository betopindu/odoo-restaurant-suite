import json
from datetime import datetime

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_ambiguous_reconciliation_service import (
    PySifenAmbiguousSubmissionReconciliationService,
)
from odoo.addons.einvoice_py.services.py_sifen_consulta_de_service import (
    PySifenConsultaDeService,
)
from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
    PySifenRuntimeCredentials,
)
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenTimeoutError,
)
from odoo.addons.einvoice_py.services.py_sifen_transmission_persistence_service import (
    PySifenTransmissionPersistenceService,
)


class _CredentialProviderStub:
    def __init__(self, credentials):
        self.credentials = credentials
        self.calls = []

    def resolve(self, *, document):
        self.calls.append(document)
        return self.credentials


class _TransportStub:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class _SubmissionPipelineStub:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def submit_test(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.result)

    def submit_production(self, **kwargs):
        raise AssertionError("Production submission must not be used.")


class TestPySifenAmbiguousSubmissionReconciliationService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"
    SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
    SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN Ambiguous Reconciliation Tenant",
            "code": "sifen-ambiguous-reconciliation",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.sequence = self.env["ir.sequence"].create({
            "name": self.id(),
            "implementation": "no_gap",
            "padding": 1,
            "number_next": 1,
        })
        self.adapter = self.env["fiscal.adapter.config"].create({
            "name": self.id(),
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "country_code": "PY",
            "adapter_code": "py_sifen",
            "environment": "test",
            "sequence_id": self.sequence.id,
            "endpoint_base_url": "https://sifen-test.example.test/de",
        })
        self.document = self.env["fiscal.document"].create({
            "name": self.id(),
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "adapter_config_id": self.adapter.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_sifen",
            "customer_name": "Test Customer",
            "amount_total": 100,
            "idempotency_key": self.id(),
            "py_cdc": self.CDC,
            "py_cdc_dv": self.CDC[-1],
            "country_identifier": self.CDC,
        })
        self.mtls_credential = self.env["fiscal.credential"].create({
            "name": self.id(),
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "provider_type": "external_secret",
            "material_format": "pkcs12",
            "secret_ref": "file:///synthetic/test.p12",
        })
        self.runtime_credentials = PySifenRuntimeCredentials(
            adapter_config=self.adapter,
            xml_signing_credential=self.mtls_credential,
            mutual_tls_credential=self.mtls_credential,
            signing_certificate_bytes=b"certificate",
            signing_private_key_bytes=b"private-key",
            signing_private_key_password=b"password",
            csc_id="0001",
            csc_value="csc-secret",
            endpoint_url="https://sifen-test.example.test/de",
            timeout_seconds=30,
        )

    def test_approved_0422_reconciles_document_and_submission(self):
        ambiguous = self._ambiguous_transmission()
        service, transport = self._reconciliation_service(
            self._response("0422", "CDC encontrado", include_content=True)
        )

        result = service.reconcile(document=self.document)

        query = self.env["fiscal.transmission"].browse(
            result["query_transmission_id"]
        )
        self.assertEqual(result["resolution_status"], "accepted")
        self.assertEqual(self.document.state, "accepted")
        self.assertEqual(self.document.authority_status, "0422")
        self.assertTrue(self.document.accepted_at)
        self.assertFalse(self.document.authority_receipt_ref)
        self.assertEqual(ambiguous.state, "accepted")
        self.assertEqual(ambiguous.authority_status_code, "0422")
        self.assertEqual(query.transmission_type, "status_query")
        self.assertEqual(query.state, "accepted")
        self.assertEqual(len(query.request_hash), 64)
        self.assertEqual(len(query.response_hash), 64)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(
            transport.calls[0]["endpoint_url"],
            PySifenConsultaDeService.TEST_ENDPOINT_URL,
        )
        self.assertEqual(
            transport.calls[0]["mutual_tls_credential"],
            self.mtls_credential,
        )
        self.assertEqual(transport.calls[0]["timeout_seconds"], 30)
        request_root = etree.fromstring(transport.calls[0]["body"])
        self.assertEqual(
            request_root.tag,
            f"{{{self.SOAP_NS}}}Envelope",
        )
        request_node = request_root.find(
            f".//{{{self.SIFEN_NS}}}rEnviConsDeRequest"
        )
        self.assertIsNotNone(request_node)
        self.assertEqual(
            request_node.find(f"{{{self.SIFEN_NS}}}dCDC").text,
            self.CDC,
        )
        self.assertTrue(
            request_node.find(f"{{{self.SIFEN_NS}}}dId").text.isdigit()
        )
        persisted_query = json.dumps(query.read()[0], default=str)
        for secret in (
            "certificate",
            "private-key",
            "password",
            "csc-secret",
            "synthetic/test.p12",
        ):
            self.assertNotIn(secret, persisted_query)

    def test_not_approved_0420_requires_operator_action(self):
        ambiguous = self._ambiguous_transmission()
        service, _transport = self._reconciliation_service(
            self._response("0420", "Documento no existe o no esta aprobado")
        )

        result = service.reconcile(cdc=self.CDC)

        self.assertEqual(
            result["resolution_status"],
            "operator_action_required",
        )
        self.assertEqual(self.document.state, "manual_review")
        self.assertEqual(self.document.authority_status, "0420")
        self.assertEqual(ambiguous.state, "failed_final")
        self.assertEqual(ambiguous.error_code, "remote_not_approved")
        self.assertEqual(ambiguous.retry_state, "not_retryable")

    def test_timeout_during_consulta_keeps_submission_ambiguous(self):
        ambiguous = self._ambiguous_transmission()
        service, _transport = self._reconciliation_service(
            None,
            error=PySifenTimeoutError(),
        )

        result = service.reconcile(document=self.document)

        query = self.env["fiscal.transmission"].browse(
            result["query_transmission_id"]
        )
        self.assertEqual(result["resolution_status"], "unresolved")
        self.assertEqual(ambiguous.error_code, "ambiguous_submission")
        self.assertEqual(self.document.state, "manual_review")
        self.assertEqual(query.state, "failed_retryable")
        self.assertEqual(query.error_code, "transport_failure")

    def test_soap_fault_keeps_submission_ambiguous(self):
        ambiguous = self._ambiguous_transmission()
        service, _transport = self._reconciliation_service(
            self._soap_fault()
        )

        result = service.reconcile(document=self.document)

        query = self.env["fiscal.transmission"].browse(
            result["query_transmission_id"]
        )
        self.assertEqual(result["resolution_status"], "unresolved")
        self.assertEqual(ambiguous.error_code, "ambiguous_submission")
        self.assertEqual(query.authority_status_code, "SOAPFault")
        self.assertEqual(query.error_code, "soap_fault")

    def test_malformed_response_keeps_submission_ambiguous(self):
        ambiguous = self._ambiguous_transmission()
        service, _transport = self._reconciliation_service(b"<not-xml")

        result = service.reconcile(document=self.document)

        query = self.env["fiscal.transmission"].browse(
            result["query_transmission_id"]
        )
        self.assertEqual(result["resolution_status"], "unresolved")
        self.assertEqual(ambiguous.error_code, "ambiguous_submission")
        self.assertEqual(query.state, "failed_final")
        self.assertEqual(query.error_code, "malformed_response")

    def test_submission_is_blocked_by_ambiguous_cdc_across_documents(self):
        self._ambiguous_transmission()
        other = self.document.copy({
            "name": self.id() + "-other",
            "idempotency_key": self.id() + "-other",
        })
        pipeline = _SubmissionPipelineStub(self._accepted_pipeline_result())
        persistence = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=pipeline,
        )

        with self.assertRaisesRegex(ValidationError, "reconciliation"):
            self._submit(persistence, other)

        self.assertEqual(pipeline.calls, [])

    def test_ambiguous_submission_result_requires_reconciliation(self):
        pipeline_result = self._accepted_pipeline_result()
        pipeline_result.update({
            "ok": False,
            "failed_stage": "test_submission",
            "error_message": "SIFEN test submission failed.",
            "submission_status": "failed_retryable",
            "authority_code": "",
            "authority_message": (
                "SIFEN test transport failed before a response was received."
            ),
            "authority_receipt_ref": "",
            "response_hash": "",
            "retryable": True,
            "retry_category": "timeout_failure",
            "ambiguous": True,
        })
        persistence = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=_SubmissionPipelineStub(
                pipeline_result
            ),
        )

        persisted = self._submit(persistence, self.document)
        transmission = self.env["fiscal.transmission"].browse(
            persisted["transmission_id"]
        )

        self.assertEqual(transmission.state, "manual_review")
        self.assertEqual(
            transmission.error_code,
            "ambiguous_submission",
        )
        self.assertEqual(self.document.state, "manual_review")
        self.assertEqual(
            json.loads(transmission.metadata_json)["resolution_status"],
            "remote_query_required",
        )

    def test_submission_is_allowed_after_0420_reconciliation(self):
        self._ambiguous_transmission()
        reconciliation, _transport = self._reconciliation_service(
            self._response("0420", "Documento no existe o no esta aprobado")
        )
        reconciliation.reconcile(document=self.document)
        pipeline = _SubmissionPipelineStub(self._accepted_pipeline_result())
        persistence = PySifenTransmissionPersistenceService(
            self.env,
            submission_pipeline_service=pipeline,
        )

        persisted = self._submit(persistence, self.document)

        self.assertTrue(persisted["result"]["ok"])
        self.assertEqual(len(pipeline.calls), 1)

    def test_approved_response_with_different_cdc_is_not_reconciled(self):
        ambiguous = self._ambiguous_transmission()
        different_cdc = "0" * 44
        service, _transport = self._reconciliation_service(
            self._response(
                "0422",
                "CDC encontrado",
                include_content=True,
                returned_cdc=different_cdc,
            )
        )

        result = service.reconcile(document=self.document)

        query = self.env["fiscal.transmission"].browse(
            result["query_transmission_id"]
        )
        self.assertEqual(result["resolution_status"], "unresolved")
        self.assertEqual(query.error_code, "cdc_mismatch")
        self.assertEqual(ambiguous.error_code, "ambiguous_submission")
        self.assertNotEqual(self.document.state, "accepted")

    def test_reconciliation_is_idempotent(self):
        self._ambiguous_transmission()
        service, transport = self._reconciliation_service(
            self._response("0422", "CDC encontrado", include_content=True)
        )

        first = service.reconcile(document=self.document)
        second = service.reconcile(document=self.document)

        self.assertEqual(first, second)
        self.assertEqual(len(transport.calls), 1)
        queries = self.env["fiscal.transmission"].search([
            ("document_id", "=", self.document.id),
            ("transmission_type", "=", "status_query"),
        ])
        self.assertEqual(len(queries), 1)

    def _reconciliation_service(self, response, error=None):
        transport = _TransportStub(
            response=(
                {
                    "status_code": 200,
                    "content": response,
                }
                if response is not None
                else None
            ),
            error=error,
        )
        provider = _CredentialProviderStub(self.runtime_credentials)
        consulta = PySifenConsultaDeService(
            self.env,
            credential_provider=provider,
            transport=transport,
        )
        return (
            PySifenAmbiguousSubmissionReconciliationService(
                self.env,
                consulta_de_service=consulta,
            ),
            transport,
        )

    def _ambiguous_transmission(self):
        self.document.with_context(
            einvoice_skip_fiscal_document_lock=True
        ).write({"state": "manual_review"})
        return self.env["fiscal.transmission"].create({
            "document_id": self.document.id,
            "transmission_type": "submit",
            "state": "manual_review",
            "country_code": "PY",
            "environment": "test",
            "country_identifier": self.CDC,
            "error_code": "ambiguous_submission",
            "error_message": "Submission result is ambiguous.",
            "metadata_json": '{"ambiguous": true}',
        })

    def _submit(self, service, document):
        return service.submit_and_persist(
            document=document,
            payload={"payload": "fixture"},
            certificate_bytes=b"certificate",
            private_key_bytes=b"private-key",
            private_key_password=b"password",
            signing_timestamp=datetime(2026, 7, 4, 12, 0, 0),
            endpoint_url="https://sifen-test.example.test/de",
        )

    def _accepted_pipeline_result(self):
        return {
            "ok": True,
            "failed_stage": "",
            "error_message": "",
            "cdc": self.CDC,
            "signed_xml_sha256": "a" * 64,
            "qr_hash": "b" * 64,
            "submission_status": "accepted",
            "authority_code": "0260",
            "authority_message": "Aprobado",
            "authority_receipt_ref": "12345",
            "request_hash": "c" * 64,
            "response_hash": "d" * 64,
            "retryable": False,
            "retry_category": "",
        }

    def _response(
        self,
        code,
        message,
        *,
        include_content=False,
        returned_cdc=None,
    ):
        content = ""
        if include_content:
            content = f"""
              <sifen:xContenDE>
                <sifen:rDE>
                  <sifen:DE Id="{returned_cdc or self.CDC}"/>
                </sifen:rDE>
              </sifen:xContenDE>
            """
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{self.SOAP_NS}"
               xmlns:sifen="{self.SIFEN_NS}">
  <soap:Body>
    <sifen:rEnviConsDeResponse>
      <sifen:dCodRes>{code}</sifen:dCodRes>
      <sifen:dMsgRes>{message}</sifen:dMsgRes>
      {content}
    </sifen:rEnviConsDeResponse>
  </soap:Body>
</soap:Envelope>""".encode("utf-8")

    def _soap_fault(self):
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{self.SOAP_NS}">
  <soap:Body>
    <soap:Fault>
      <soap:Code><soap:Value>soap:Receiver</soap:Value></soap:Code>
      <soap:Reason><soap:Text>internal detail</soap:Text></soap:Reason>
    </soap:Fault>
  </soap:Body>
</soap:Envelope>""".encode("utf-8")
