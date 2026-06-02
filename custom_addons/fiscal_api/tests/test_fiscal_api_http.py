import json

from odoo.tests import HttpCase
from odoo.tests.common import get_db_name

from odoo.addons.fiscal_api.services.authentication import FiscalApiAuthenticationService


class TestFiscalApiHttp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant_a = cls.env["fiscal.tenant"].create({
            "name": "API Tenant A",
            "code": "api-a",
            "company_id": cls.env.company.id,
        })
        cls.tenant_b = cls.env["fiscal.tenant"].create({
            "name": "API Tenant B",
            "code": "api-b",
            "company_id": cls.env.company.id,
        })
        cls.raw_key_a = "fapi_test_key_a"
        cls.raw_key_b = "fapi_test_key_b"
        cls.api_key_a = cls._create_api_key(
            "API Key A",
            cls.tenant_a,
            cls.raw_key_a,
        )
        cls.api_key_b = cls._create_api_key(
            "API Key B",
            cls.tenant_b,
            cls.raw_key_b,
        )

    @classmethod
    def _create_api_key(cls, name, tenant, raw_key):
        authentication = FiscalApiAuthenticationService(cls.env)
        return cls.env["fiscal.api.key"].sudo().create({
            "name": name,
            "tenant_id": tenant.id,
            "company_id": cls.env.company.id,
            "key_prefix": authentication.key_prefix(raw_key),
            "key_hash": authentication.hash_key(raw_key),
            "default_processing_mode": "async",
        })

    def setUp(self):
        super().setUp()
        self.url_open(f"/web/login?db={get_db_name()}")

    def _payload(self, key, processing_mode="async", reference=None):
        return {
            "idempotency_key": key,
            "processing_mode": processing_mode,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "fake",
            "source": {
                "reference": reference or key,
            },
            "customer": {
                "name": "API Test Customer",
            },
            "amounts": {
                "total": 100,
            },
            "lines": [
                {
                    "product_name": "API Test Item",
                    "quantity": 1,
                    "price_unit": 100,
                    "total": 100,
                },
            ],
        }

    def _headers(self, raw_key):
        return {
            "Authorization": f"Bearer {raw_key}",
            "Content-Type": "application/json",
        }

    def _post_document(self, raw_key, payload):
        return self.url_open(
            "/api/v1/fiscal/documents",
            data=json.dumps(payload),
            headers=self._headers(raw_key),
            allow_redirects=False,
        )

    def _get_status(self, raw_key, uuid):
        return self.url_open(
            f"/api/v1/fiscal/documents/{uuid}",
            headers=self._headers(raw_key),
            allow_redirects=False,
        )

    def _document_by_uuid(self, uuid):
        return self.env["fiscal.document"].sudo().search(
            [("uuid", "=", uuid)],
            limit=1,
        )

    def test_invalid_api_key_returns_401(self):
        response = self._post_document(
            "not-a-valid-key",
            self._payload("invalid-key-test"),
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_api_key")

    def test_post_async_creates_queued_document(self):
        response = self._post_document(
            self.raw_key_a,
            self._payload("async-create-test"),
        )

        self.assertEqual(response.status_code, 202)
        data = response.json()["data"]
        self.assertTrue(data["uuid"])
        self.assertEqual(data["state"], "queued")
        self.assertEqual(data["processing_mode"], "async")
        self.assertEqual(data["idempotency_key"], "async-create-test")
        self.assertEqual(
            data["status_url"],
            f"/api/v1/fiscal/documents/{data['uuid']}",
        )
        document = self._document_by_uuid(data["uuid"])
        self.assertTrue(document)
        self.assertEqual(document.tenant_id, self.tenant_a)

    def test_get_status_same_tenant_returns_document(self):
        create_response = self._post_document(
            self.raw_key_a,
            self._payload("status-test"),
        )
        uuid = create_response.json()["data"]["uuid"]

        response = self._get_status(self.raw_key_a, uuid)

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["uuid"], uuid)
        self.assertEqual(data["document_type"], "invoice")
        self.assertEqual(data["state"], "queued")
        self.assertEqual(data["country_code"], "PY")
        self.assertEqual(data["environment"], "test")
        self.assertEqual(data["source_reference"], "status-test")
        self.assertEqual(data["idempotency_key"], "status-test")
        self.assertIn("authority_status", data)
        self.assertIn("authority_receipt_ref", data)
        self.assertIn("submitted_at", data)
        self.assertIn("accepted_at", data)

    def test_cross_tenant_get_returns_404(self):
        create_response = self._post_document(
            self.raw_key_a,
            self._payload("cross-tenant-test"),
        )
        uuid = create_response.json()["data"]["uuid"]

        response = self._get_status(self.raw_key_b, uuid)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "document_not_found")

    def test_duplicate_idempotency_post_returns_existing_document(self):
        payload = self._payload("idempotency-replay-test")
        first_response = self._post_document(self.raw_key_a, payload)
        second_response = self._post_document(self.raw_key_a, payload)

        self.assertEqual(first_response.status_code, 202)
        self.assertEqual(second_response.status_code, 202)
        first_uuid = first_response.json()["data"]["uuid"]
        second_uuid = second_response.json()["data"]["uuid"]
        self.assertEqual(first_uuid, second_uuid)
        documents = self.env["fiscal.document"].sudo().search([
            ("tenant_id", "=", self.tenant_a.id),
            ("document_type", "=", "invoice"),
            ("idempotency_key", "=", "idempotency-replay-test"),
        ])
        self.assertEqual(len(documents), 1)

    def test_sync_post_creates_payload_attachments(self):
        response = self._post_document(
            self.raw_key_a,
            self._payload("payload-attachment-test", processing_mode="sync"),
        )

        self.assertEqual(response.status_code, 201)
        uuid = response.json()["data"]["uuid"]
        document = self._document_by_uuid(uuid)
        attachments = self.env["fiscal.attachment"].sudo().search([
            ("document_id", "=", document.id),
            ("attachment_type", "in", ["canonical_json", "authority_response"]),
        ])
        self.assertEqual(
            set(attachments.mapped("attachment_type")),
            {"canonical_json", "authority_response"},
        )
        for attachment in attachments:
            self.assertEqual(attachment.mimetype, "application/json")
            self.assertTrue(attachment.sha256)
            self.assertTrue(attachment.ir_attachment_id)
