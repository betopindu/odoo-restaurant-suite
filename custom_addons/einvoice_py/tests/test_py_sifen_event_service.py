import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
import xmlsec

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_credential_provider import PySifenRuntimeCredentials
from odoo.addons.einvoice_py.services.py_sifen_event_service import (
    PySifenCancellationService, PySifenEventService, PySifenInutilizationService,
)
from odoo.addons.einvoice_py.services.py_sifen_event_signature_service import PySifenEventSignatureService
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import PySifenTimeoutError


class _Provider:
    def __init__(self, credentials):
        self.credentials = credentials

    def resolve_event(self, *, adapter_config):
        return self.credentials


class _Signer:
    def sign(self, *, event_xml_bytes, **kwargs):
        return SimpleNamespace(signed_xml_bytes=event_xml_bytes, event_id="1")


class _Transport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class TestPySifenEventService(TransactionCase):
    CDC = "01444444017001001001452822017012515873260988"

    def setUp(self):
        super().setUp()
        self.tenant = self.env["fiscal.tenant"].create({"name": self.id(), "code": self.id(), "company_id": self.env.company.id})
        self.sequence = self.env["ir.sequence"].create({"name": self.id(), "implementation": "no_gap", "padding": 1})
        self.adapter = self.env["fiscal.adapter.config"].create({
            "name": self.id(), "tenant_id": self.tenant.id, "company_id": self.env.company.id,
            "country_code": "PY", "adapter_code": "py_sifen", "environment": "test",
            "sequence_id": self.sequence.id, "endpoint_base_url": "https://sifen-test.example.test/de",
        })
        self.issuer = self.env["fiscal.py.issuer"].create({
            "name": self.id(), "ruc": "44444401", "ruc_dv": "7", "taxpayer_type": "2",
            "tenant_id": self.tenant.id, "company_id": self.env.company.id, "environment": "test", "active": False,
        })
        self.establishment = self.env["fiscal.py.establishment"].create({
            "name": "Main", "code": "001", "tenant_id": self.tenant.id, "company_id": self.env.company.id,
            "issuer_id": self.issuer.id, "active": True,
        })
        self.point = self.env["fiscal.py.point.of.issue"].create({"name": "POS", "code": "001", "establishment_id": self.establishment.id})
        self.timbrado = self.env["fiscal.py.timbrado"].create({
            "number": "44444401", "tenant_id": self.tenant.id, "company_id": self.env.company.id,
            "environment": "test", "document_type": "invoice",
        })
        self.document = self.env["fiscal.document"].create({
            "name": self.id(), "tenant_id": self.tenant.id, "company_id": self.env.company.id,
            "adapter_config_id": self.adapter.id, "document_type": "invoice", "country_code": "PY",
            "environment": "test", "adapter_code": "py_sifen", "customer_name": "Customer", "amount_total": 100,
            "idempotency_key": self.id(), "py_cdc": self.CDC, "country_identifier": self.CDC,
            "py_document_number": "0000001", "py_timbrado_id": self.timbrado.id,
            "py_establishment_id": self.establishment.id, "py_point_of_issue_id": self.point.id,
        })
        self.document.with_context(einvoice_skip_fiscal_document_lock=True).write({
            "state": "accepted", "accepted_at": datetime.now() - timedelta(hours=1), "authority_status": "0260",
        })
        self.env["fiscal.transmission"].create({
            "document_id": self.document.id, "transmission_type": "submit", "state": "accepted",
            "country_code": "PY", "environment": "test", "country_identifier": self.CDC,
            "request_hash": "a" * 64, "response_hash": "b" * 64,
        })
        credential = self.env["fiscal.credential"].create({
            "name": self.id(), "tenant_id": self.tenant.id, "company_id": self.env.company.id,
            "provider_type": "external_secret", "material_format": "pkcs12", "secret_ref": "file:///safe/test.p12",
        })
        self.credentials = PySifenRuntimeCredentials(
            adapter_config=self.adapter, xml_signing_credential=credential, mutual_tls_credential=credential,
            signing_certificate_bytes=b"certificate", signing_private_key_bytes=b"private-key",
            signing_private_key_password=b"password", csc_id="", csc_value="", endpoint_url="", timeout_seconds=30,
        )

    def test_accepted_cancellation_preserves_submission_evidence(self):
        service, transport = self._cancellation(self._response("0600", "Evento registrado correctamente"))
        original = self.document.transmission_ids.filtered(lambda tx: tx.transmission_type == "submit")
        before = (original.state, original.request_hash, original.response_hash, self.document.accepted_at)
        result = service.cancel(document=self.document, reason="Transaction did not occur")
        self.assertTrue(result["accepted"])
        self.assertEqual(self.document.state, "cancelled")
        self.assertEqual((original.state, original.request_hash, original.response_hash, self.document.accepted_at), before)
        cancellation = self.env["fiscal.transmission"].browse(result["transmission_id"])
        self.assertEqual(cancellation.state, "accepted")
        self.assertEqual(cancellation.authority_status_code, "0600")
        self.assertEqual(cancellation.http_status, 200)
        self.assertEqual(len(transport.calls), 1)
        request = etree.fromstring(transport.calls[0]["body"])
        self.assertIsNotNone(request.find(".//{http://ekuatia.set.gov.py/sifen/xsd}rEnviEventoDe"))
        self.assertIsNotNone(request.find(".//{http://ekuatia.set.gov.py/sifen/xsd}rGeVeCan"))
        self.assertNotIn(b"CSC", transport.calls[0]["body"])

    def test_non_accepted_and_expired_documents_are_blocked(self):
        service, transport = self._cancellation(self._response("0600", "OK"))
        self.document.with_context(einvoice_skip_fiscal_document_lock=True).write({"state": "rejected"})
        with self.assertRaisesRegex(ValidationError, "accepted"):
            service.cancel(document=self.document, reason="Valid reason")
        self.document.with_context(einvoice_skip_fiscal_document_lock=True).write({"state": "accepted", "accepted_at": datetime.now() - timedelta(hours=49)})
        with self.assertRaisesRegex(ValidationError, "window"):
            service.cancel(document=self.document, reason="Valid reason")
        self.assertEqual(transport.calls, [])

    def test_cancellation_rejection_preserves_accepted_state(self):
        service, _transport = self._cancellation(self._response("1600", "Rejected event"))
        result = service.cancel(document=self.document, reason="Transaction did not occur")
        self.assertFalse(result["accepted"])
        self.assertEqual(self.document.state, "accepted")
        self.assertEqual(self.env["fiscal.transmission"].browse(result["transmission_id"]).state, "rejected")

    def test_cancellation_timeout_is_manual_review_and_never_retried(self):
        service, transport = self._cancellation(None, error=PySifenTimeoutError())
        result = service.cancel(document=self.document, reason="Transaction did not occur")
        self.assertTrue(result["ambiguous"])
        self.assertEqual(self.document.state, "accepted")
        self.assertEqual(self.env["fiscal.transmission"].browse(result["transmission_id"]).state, "manual_review")
        self.assertEqual(len(transport.calls), 1)
        with self.assertRaisesRegex(ValidationError, "unresolved"):
            service.cancel(document=self.document, reason="Transaction did not occur")
        self.assertEqual(len(transport.calls), 1)

    def test_cancelled_document_is_idempotent(self):
        service, transport = self._cancellation(self._response("0600", "OK"))
        first = service.cancel(document=self.document, reason="Transaction did not occur")
        second = service.cancel(document=self.document, reason="Transaction did not occur")
        self.assertTrue(second["idempotent"])
        self.assertEqual(first["transmission_id"], second["transmission_id"])
        self.assertEqual(len(transport.calls), 1)

    def test_valid_inutilization_and_idempotency(self):
        service, transport = self._inutilization(self._response("0600", "Evento registrado correctamente"))
        kwargs = self._inutilization_kwargs(10, 12)
        first = service.inutilize(**kwargs)
        second = service.inutilize(**kwargs)
        record = self.env["fiscal.py.inutilization"].browse(first["inutilization_id"])
        self.assertTrue(first["accepted"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(record.state, "accepted")
        self.assertEqual(len(transport.calls), 1)

    def test_inutilization_blocks_issued_overlap_and_existing_overlap(self):
        service, _transport = self._inutilization(self._response("0600", "OK"))
        with self.assertRaisesRegex(ValidationError, "issued"):
            service.inutilize(**self._inutilization_kwargs(1, 2))
        service.inutilize(**self._inutilization_kwargs(10, 20))
        with self.assertRaisesRegex(ValidationError, "overlaps existing"):
            service.inutilize(**self._inutilization_kwargs(15, 25))

    def test_invalid_inutilization_ranges_are_blocked(self):
        service, transport = self._inutilization(self._response("0600", "OK"))
        for start, end in ((0, 1), (5, 4), (1, 1001)):
            with self.assertRaisesRegex(ValidationError, "range"):
                service.inutilize(**self._inutilization_kwargs(start, end))
        self.assertEqual(transport.calls, [])

    def test_inutilization_scope_is_tenant_and_company_isolated(self):
        service, transport = self._inutilization(self._response("0600", "OK"))
        other_tenant = self.env["fiscal.tenant"].create({
            "name": self.id() + "-other", "code": self.id() + "-other",
            "company_id": self.env.company.id,
        })
        other_adapter = self.adapter.copy({
            "name": self.id() + "-other", "tenant_id": other_tenant.id,
        })
        kwargs = self._inutilization_kwargs(30, 31)
        kwargs["adapter"] = other_adapter
        with self.assertRaisesRegex(ValidationError, "scope"):
            service.inutilize(**kwargs)
        self.assertEqual(transport.calls, [])

    def test_row_locks_are_taken_before_event_validation(self):
        cancellation, _transport = self._cancellation(self._response("0600", "OK"))
        cancellation._lock(self.document)
        inutilization, _transport = self._inutilization(self._response("0600", "OK"))
        inutilization._lock_scope(self.timbrado)
        self.assertTrue(self.document.exists())
        self.assertTrue(self.timbrado.exists())

    def test_security_metadata_excludes_secret_material(self):
        service, _transport = self._cancellation(self._response("0600", "OK"))
        result = service.cancel(document=self.document, reason="Transaction did not occur")
        values = json.dumps(self.env["fiscal.transmission"].browse(result["transmission_id"]).read()[0], default=str)
        for secret in ("private-key", "password", "certificate", "safe/test.p12"):
            self.assertNotIn(secret, values)

    def test_event_signature_is_cryptographically_valid_and_references_event_id(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Event Test")])
        certificate = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now() - timedelta(days=1))
            .not_valid_after(datetime.now() + timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        xml = PySifenEventService(self.env).build_cancellation_event(
            event_id="123", cdc=self.CDC, reason="Transaction did not occur",
            signing_timestamp=fields.Datetime.now(),
        )
        result = PySifenEventSignatureService().sign(
            event_xml_bytes=xml,
            certificate_bytes=certificate.public_bytes(serialization.Encoding.PEM),
            private_key_bytes=key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
        root = etree.fromstring(result.signed_xml_bytes)
        signature = root.find("{http://www.w3.org/2000/09/xmldsig#}Signature")
        self.assertEqual(
            signature.find(".//{http://www.w3.org/2000/09/xmldsig#}Reference").get("URI"),
            "#123",
        )
        xmlsec.tree.add_ids(root, ["Id"])
        verify_key = xmlsec.Key.from_memory(
            certificate.public_bytes(serialization.Encoding.PEM),
            xmlsec.constants.KeyDataFormatCertPem,
        )
        context = xmlsec.SignatureContext()
        context.key = verify_key
        context.verify(signature)

    def _event_service(self, response, error=None):
        transport = _Transport(response=response, error=error)
        return PySifenEventService(self.env, credential_provider=_Provider(self.credentials), signer=_Signer(), transport=transport), transport

    def _cancellation(self, response, error=None):
        event, transport = self._event_service(response, error)
        return PySifenCancellationService(self.env, event_service=event), transport

    def _inutilization(self, response, error=None):
        event, transport = self._event_service(response, error)
        return PySifenInutilizationService(self.env, event_service=event), transport

    def _inutilization_kwargs(self, start, end):
        return {
            "adapter": self.adapter, "timbrado": self.timbrado, "establishment": self.establishment,
            "point_of_issue": self.point, "document_type": "invoice", "number_from": start,
            "number_to": end, "reason": "Unused numbering range", "occurred_on": fields.Date.today(),
        }

    def _response(self, code, message):
        body = f'''<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:s="http://ekuatia.set.gov.py/sifen/xsd"><soap:Body><s:rRetEnviEventoDe><s:dFecProc>2026-08-09T12:00:00-03:00</s:dFecProc><s:gResProcEVe><s:dEstRes>Procesado</s:dEstRes><s:dProtAut>123</s:dProtAut><s:id>1</s:id><s:gResProc><s:dCodRes>{code}</s:dCodRes><s:dMsgRes>{message}</s:dMsgRes></s:gResProc></s:gResProcEVe></s:rRetEnviEventoDe></soap:Body></soap:Envelope>'''
        return {"status_code": 200, "content": body.encode()}
