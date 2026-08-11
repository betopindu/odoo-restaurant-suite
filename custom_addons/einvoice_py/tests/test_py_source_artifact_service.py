import base64
import hashlib
import json

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_source_artifact_service import (
    PySourceArtifactService,
)


class TestPySourceArtifactService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "Source artifact tenant",
            "code": "source-artifact",
            "company_id": cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.document = self.env["fiscal.document"].create({
            "name": "Source artifact document",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Customer",
            "amount_total": 100,
            "idempotency_key": self.id(),
            "py_cdc": self.CDC,
            "country_identifier": self.CDC,
        })
        self.service = PySourceArtifactService(self.env)

    def _payload(self, marker="current"):
        return {
            "cdc": self.CDC,
            "document": {"py_cdc": self.CDC},
            "marker": marker,
        }

    def test_payload_is_versioned_and_only_current_is_resolved(self):
        first = self.service.persist_payload(
            document=self.document, payload=self._payload("first")
        )
        second = self.service.persist_payload(
            document=self.document, payload=self._payload("second")
        )
        current, payload = self.service.read_current_payload(document=self.document)

        self.assertEqual(current, second)
        self.assertEqual(payload["marker"], "second")
        self.assertEqual(json.loads(first.metadata_json)["artifact_status"], "superseded")
        self.assertEqual(json.loads(second.metadata_json)["artifact_status"], "current")

    def test_identical_payload_is_idempotent(self):
        first = self.service.persist_payload(document=self.document, payload=self._payload())
        second = self.service.persist_payload(document=self.document, payload=self._payload())
        self.assertEqual(first, second)
        self.assertEqual(self.env["fiscal.attachment"].search_count([
            ("document_id", "=", self.document.id),
            ("attachment_type", "=", "paraguay_payload_json"),
        ]), 1)

    def test_ambiguous_legacy_payloads_fail_closed(self):
        for marker in ("one", "two"):
            self.env["fiscal.attachment"].create_json_payload_attachment(
                self.document,
                "paraguay_payload_json",
                f"{marker}.json",
                self._payload(marker),
            )
        with self.assertRaisesRegex(ValidationError, "cannot be resolved safely"):
            self.service.read_current_payload(document=self.document)

    def test_single_legacy_payload_is_compatible_when_integrity_and_cdc_match(self):
        legacy = self.env["fiscal.attachment"].create_json_payload_attachment(
            self.document,
            "paraguay_payload_json",
            "legacy.json",
            self._payload("legacy"),
        )
        current, payload = self.service.read_current_payload(document=self.document)
        self.assertEqual(current, legacy)
        self.assertEqual(payload["marker"], "legacy")
        self.assertFalse(json.loads(legacy.metadata_json or "{}").get("artifact_status"))

    def test_payload_hash_and_cdc_mismatch_fail_closed(self):
        attachment = self.service.persist_payload(document=self.document, payload=self._payload())
        attachment.sha256 = "0" * 64
        with self.assertRaisesRegex(ValidationError, "integrity"):
            self.service.read_current_payload(document=self.document)

        attachment.sha256 = hashlib.sha256(base64.b64decode(
            attachment.ir_attachment_id.datas
        )).hexdigest()
        wrong = dict(self._payload(), cdc="1" * 44)
        with self.assertRaisesRegex(ValidationError, "CDC"):
            self.service.persist_payload(document=self.document, payload=wrong)

    def test_unsigned_xml_versions_link_to_current_payload(self):
        first_payload = self.service.persist_payload(
            document=self.document, payload=self._payload("one")
        )
        first = self.service.persist_unsigned_xml(
            document=self.document,
            unsigned_xml_bytes=b"<first/>",
            payload_attachment=first_payload,
        )
        second_payload = self.service.persist_payload(
            document=self.document, payload=self._payload("two")
        )
        second = self.service.persist_unsigned_xml(
            document=self.document,
            unsigned_xml_bytes=b"<second/>",
            payload_attachment=second_payload,
        )
        current, content = self.service.read_current_unsigned_xml(
            document=self.document, payload_attachment=second_payload
        )
        self.assertEqual((current, content), (second, b"<second/>"))
        self.assertEqual(json.loads(first.metadata_json)["artifact_status"], "superseded")
        self.assertEqual(json.loads(second.metadata_json)["payload_attachment_id"], second_payload.id)
