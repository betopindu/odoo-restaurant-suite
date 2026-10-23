from types import SimpleNamespace

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_ruc_query_service import (
    PySifenRucQueryService,
)
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenTimeoutError,
)


class _Credentials:
    def resolve_event(self, *, adapter_config):
        return SimpleNamespace(timeout_seconds=5, mutual_tls_credential=object())


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


@tagged("post_install", "-at_install")
class TestPySifenRucQueryService(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "RUC query tenant",
            "company_id": cls.company.id,
        })
        cls.sequence = cls.env["ir.sequence"].create({
            "name": "RUC query ids",
            "padding": 1,
            "number_next": 1,
        })
        cls.adapter = cls.env["fiscal.adapter.config"].create({
            "name": "RUC query adapter",
            "tenant_id": cls.tenant.id,
            "company_id": cls.company.id,
            "country_code": "PY",
            "adapter_code": "sifen",
            "environment": "test",
            "sequence_id": cls.sequence.id,
        })

    def _response(self, code="0502", include_container=True, ruc="80012345"):
        ns = PySifenRucQueryService.SIFEN_NS
        soap = PySifenRucQueryService.SOAP_ENV_NS
        envelope = etree.Element(f"{{{soap}}}Envelope", nsmap={"soap": soap, "s": ns})
        body = etree.SubElement(envelope, f"{{{soap}}}Body")
        response = etree.SubElement(body, f"{{{ns}}}rResEnviConsRUC")
        etree.SubElement(response, f"{{{ns}}}dCodRes").text = code
        etree.SubElement(response, f"{{{ns}}}dMsgRes").text = (
            "RUC encontrado" if code == "0502" else "RUC no existe"
        )
        if include_container:
            container = etree.SubElement(response, f"{{{ns}}}xContRUC")
            etree.SubElement(container, f"{{{ns}}}dRUCCons").text = ruc
            etree.SubElement(container, f"{{{ns}}}dRazCons").text = "CLIENTE AUTORIDAD SA"
            etree.SubElement(container, f"{{{ns}}}dCodEstCons").text = "ACT"
            etree.SubElement(container, f"{{{ns}}}dDesEstCons").text = "ACTIVO"
            etree.SubElement(container, f"{{{ns}}}dRUCFactElec").text = "S"
        return {"status_code": 200, "content": etree.tostring(envelope)}

    def _service(self, transport):
        return PySifenRucQueryService(
            self.env,
            credential_provider=_Credentials(),
            transport=transport,
        )

    def test_local_first_does_not_call_transport(self):
        partner = self.env["res.partner"].create({
            "name": "Local taxpayer",
            "vat": "80012345-6",
            "py_sifen_receiver_profile": "taxpayer",
            "py_sifen_taxpayer_type": "2",
        })
        transport = _Transport(error=AssertionError("transport must not run"))
        result = self._service(transport).resolve(
            adapter_config=self.env["fiscal.adapter.config"],
            company=self.company,
            ruc="80012345-6",
            allow_remote=False,
        )
        self.assertEqual(result["source"], "local")
        self.assertEqual(result["partner_id"], partner.id)
        self.assertFalse(transport.calls)

    def test_authority_found_persists_reusable_local_partner(self):
        transport = _Transport(response=self._response(ruc="80012346"))
        result = self._service(transport).resolve(
            adapter_config=self.adapter,
            company=self.company,
            ruc="80012346-7",
        )
        self.assertEqual(result["source"], "authority")
        partner = self.env["res.partner"].browse(result["partner_id"])
        self.assertEqual(partner.name, "CLIENTE AUTORIDAD SA")
        self.assertEqual(partner.vat, "80012346-7")
        self.assertEqual(partner.py_sifen_ruc_resolution, "authority")
        self.assertEqual(len(transport.calls), 1)

    def test_not_found_and_timeout_allow_explicit_manual_fallback(self):
        not_found = self._service(_Transport(response=self._response("0500", False))).resolve(
            adapter_config=self.adapter,
            company=self.company,
            ruc="80012347-8",
        )
        self.assertEqual(not_found["status"], "manual_required")
        self.assertEqual(not_found["reason"], "authority_not_found")
        timeout = self._service(_Transport(error=PySifenTimeoutError())).resolve(
            adapter_config=self.adapter,
            company=self.company,
            ruc="80012348-9",
        )
        self.assertEqual(timeout["reason"], "authority_unavailable")

    def test_http_error_has_sanitized_structural_diagnostic_without_retry(self):
        secret_body = b"<html><body>gateway detail SECRET-TOKEN</body></html>"
        transport = _Transport(response={
            "status_code": 400,
            "content": secret_body,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
        })

        result = self._service(transport).resolve(
            adapter_config=self.adapter,
            company=self.company,
            ruc="80012350-1",
        )

        self.assertEqual(result["reason"], "authority_invalid_response")
        self.assertEqual(result["http_status"], 400)
        self.assertEqual(result["response_diagnostic"], {
            "category": "html",
            "content_type": "text/html",
            "byte_length": len(secret_body),
        })
        self.assertNotIn("SECRET-TOKEN", repr(result))
        self.assertEqual(len(transport.calls), 1)

    def test_malformed_soap_response_has_no_raw_payload_diagnostic(self):
        raw_body = b"<soap:Envelope>PRIVATE-RUC-DATA"
        result = self._service(_Transport()).normalize_response(
            response={
                "status_code": 200,
                "content": raw_body,
                "headers": {"Content-Type": "application/soap+xml"},
            },
            expected_ruc="80012350",
        )

        self.assertEqual(result["response_diagnostic"], {
            "category": "malformed_xml",
            "content_type": "application/soap+xml",
            "byte_length": len(raw_body),
        })
        self.assertNotIn("PRIVATE-RUC-DATA", repr(result))

    def test_manual_partner_is_marked_unverified(self):
        result = self._service(_Transport()).create_manual_partner(
            company=self.company,
            ruc="80012349-0",
            name="Manual Customer",
            taxpayer_type="2",
            email="manual@example.com",
        )
        partner = self.env["res.partner"].browse(result["partner_id"])
        self.assertEqual(result["source"], "manual_unverified")
        self.assertEqual(partner.py_sifen_ruc_resolution, "manual_unverified")
        self.assertEqual(partner.email, "manual@example.com")

    def test_ruc_requires_verification_digit(self):
        with self.assertRaisesRegex(ValidationError, "verification digit"):
            PySifenRucQueryService.normalize_ruc("80012345")
