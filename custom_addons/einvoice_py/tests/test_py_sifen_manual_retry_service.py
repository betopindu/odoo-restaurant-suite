from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_authority_incident_service import (
    PySifenAuthorityIncidentService,
)
from odoo.addons.einvoice_py.services.py_sifen_manual_retry_service import (
    PySifenManualRetryService,
)
from odoo.addons.einvoice_py.services.py_sifen_datetime_service import (
    PySifenDatetimeService,
)
from odoo.addons.einvoice_py.services.py_signed_xml_attachment_service import (
    PySignedXmlAttachmentService,
)


class _PersistenceStub:
    def __init__(self):
        self.calls = []

    def submit_and_persist(self, **kwargs):
        self.calls.append(kwargs)
        return {"transmission_id": 999, "result": {"submission_status": "rejected"}}


class TestPySifenManualRetryService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN Manual Retry Tenant",
            "code": "sifen-manual-retry",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "Manual retry document",
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
            "state": "rejected",
        })
        self.persistence = _PersistenceStub()
        self.service = PySifenManualRetryService(
            self.env, persistence_service=self.persistence
        )
        self.payload = {
            "cdc": self.CDC,
            "document": {"py_cdc": self.CDC},
            "safe": "payload",
        }
        self._transmission(code="0100", message="Error Inesperado(PKI).")

    def _transmission(self, *, code, message, state="rejected", metadata="{}"):
        return self.env["fiscal.transmission"].create({
            "document_id": self.document.id,
            "transmission_type": "submit",
            "state": state,
            "country_code": "PY",
            "environment": "test",
            "country_identifier": self.CDC,
            "authority_status_code": code,
            "authority_message": message,
            "metadata_json": metadata,
        })

    def test_exact_pki_incident_is_manual_only(self):
        result = PySifenAuthorityIncidentService().classify(
            authority_code="0100", authority_message="  Error inesperado (PKI). "
        )
        self.assertEqual(result.incident_type, "transient_authority_incident")
        self.assertTrue(result.manual_retry_allowed)
        self.assertFalse(result.automatic_retry_allowed)

    def test_other_0100_message_is_not_incident(self):
        result = PySifenAuthorityIncidentService().classify(
            authority_code="0100", authority_message="CDC inexistente"
        )
        self.assertFalse(result.incident_type)
        self.assertFalse(result.manual_retry_allowed)

    def test_explicit_rejection_can_delegate_controlled_retry(self):
        result = self.service.retry(
            document=self.document,
            payload=self.payload,
            signing_timestamp=datetime(2026, 8, 7, 14, 0, 0),
        )
        self.assertEqual(result["transmission_id"], 999)
        self.assertEqual(len(self.persistence.calls), 1)
        self.assertNotIn("signed_xml_bytes", self.persistence.calls[0])

    def test_accepted_document_is_blocked(self):
        self.document.state = "accepted"
        with self.assertRaisesRegex(ValidationError, "accepted"):
            self.service.validate(
                document=self.document,
                signing_timestamp=datetime(2026, 8, 7, 14, 0, 0),
            )

    def test_ambiguous_transmission_is_blocked(self):
        self._transmission(code="", message="", state="manual_review")
        with self.assertRaisesRegex(ValidationError, "ambiguous"):
            self.service.validate(
                document=self.document,
                signing_timestamp=datetime(2026, 8, 7, 14, 0, 0),
            )

    def test_stale_signed_artifact_is_blocked(self):
        signing_timestamp = datetime(2026, 8, 7, 15, 0, 0)
        PySignedXmlAttachmentService(self.env).persist(
            document=self.document,
            signed_xml_bytes=b"signed-fixture",
            filename="signed.xml",
            metadata={
                "signing_time": PySifenDatetimeService.format_signing_datetime(
                    signing_timestamp
                )
            },
        )
        with self.assertRaisesRegex(ValidationError, "fresh signing timestamp"):
            self.service.retry(
                document=self.document,
                payload=self.payload,
                signing_timestamp=signing_timestamp,
            )
        self.assertEqual(self.persistence.calls, [])

    def test_proven_not_posted_attempt_does_not_hide_last_authority_rejection(self):
        self._transmission(
            code="",
            message="SIFEN POST was not started for this durable attempt.",
            state="failed_final",
        ).write({"error_code": "pre_post_not_attempted"})

        classification = self.service.validate(
            document=self.document,
            signing_timestamp=datetime(2026, 8, 7, 14, 0, 0),
        )

        self.assertTrue(classification.manual_retry_allowed)
