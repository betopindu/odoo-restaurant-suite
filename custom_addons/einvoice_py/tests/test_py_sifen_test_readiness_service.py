from datetime import date

from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_sifen_test_readiness_service import (
    PySifenTestReadinessService,
)


class _CertificateValidationStub:
    def __init__(self, valid=True):
        self.valid = valid
        self.calls = []

    def validate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "valid": self.valid,
            "status": "valid" if self.valid else "invalid",
        }


class TestPySifenTestReadinessService(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "SIFEN TEST Readiness Tenant",
            "code": "sifen-test-readiness",
            "company_id": cls.company.id,
        })

    def setUp(self):
        super().setUp()
        self.sequence = self.env["ir.sequence"].create({
            "name": self.id(),
            "implementation": "no_gap",
        })
        self.adapter = self.env["fiscal.adapter.config"].create({
            "name": self.id(),
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "country_code": "PY",
            "adapter_code": "py_sifen",
            "environment": "test",
            "credentials_mode": "external_secret",
            "sequence_id": self.sequence.id,
            "endpoint_base_url": "https://sifen-test.example.test/de",
        })
        self.issuer = self.env["fiscal.py.issuer"].create({
            "name": self.id(),
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "environment": "test",
            "ruc": "80012345",
            "ruc_dv": "6",
            "taxpayer_type": "2",
        })
        self.establishment = self.env["fiscal.py.establishment"].create({
            "name": self.id(),
            "code": "001",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "issuer_id": self.issuer.id,
        })
        self.point = self.env["fiscal.py.point.of.issue"].create({
            "name": self.id(),
            "code": "002",
            "establishment_id": self.establishment.id,
        })
        self.timbrado = self.env["fiscal.py.timbrado"].create({
            "number": self.issuer.ruc,
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "environment": "test",
            "document_type": "invoice",
            "valid_from": date(2026, 1, 15),
            "allowed_point_of_issue_ids": [(6, 0, [self.point.id])],
        })
        self.csc = self.env["fiscal.py.csc"].create({
            "name": self.id(),
            "id_csc": "0001",
            "csc_value": "local-readiness-csc-fixture",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "environment": "test",
        })
        self.document = self.env["fiscal.document"].create({
            "name": self.id(),
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "adapter_config_id": self.adapter.id,
            "document_type": "invoice",
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_sifen",
            "customer_name": "Readiness Customer",
            "amount_total": 100,
            "idempotency_key": self.id(),
            "py_issuer_id": self.issuer.id,
            "py_establishment_id": self.establishment.id,
            "py_point_of_issue_id": self.point.id,
            "py_timbrado_id": self.timbrado.id,
            "py_csc_id": self.csc.id,
        })

    def test_complete_fiscal_data_without_certificate_is_not_ready(self):
        validator = _CertificateValidationStub()

        report = self._service(validator).check(document=self.document)

        self.assertFalse(report["ready"])
        self.assertTrue(report["fiscal_configuration_ready"])
        self.assertTrue(report["csc_configured"])
        self.assertEqual(
            report["status"],
            "certificate_reference_missing",
        )
        self.assertEqual(validator.calls, [])

    def test_missing_csc_is_reported_before_certificate(self):
        self.document.py_csc_id = False
        validator = _CertificateValidationStub()

        report = self._service(validator).check(document=self.document)

        self.assertFalse(report["ready"])
        self.assertTrue(report["fiscal_configuration_ready"])
        self.assertEqual(report["status"], "csc_missing")
        self.assertEqual(validator.calls, [])

    def test_complete_configuration_is_ready(self):
        credential = self._credential()
        validator = _CertificateValidationStub(valid=True)

        report = self._service(validator).check(document=self.document)

        self.assertTrue(report["ready"])
        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["fiscal_configuration_ready"])
        self.assertTrue(report["csc_configured"])
        self.assertTrue(report["certificate_reference_configured"])
        self.assertTrue(report["certificate_password_configured"])
        self.assertTrue(report["certificate_valid"])
        self.assertEqual(len(validator.calls), 1)
        self.assertEqual(
            validator.calls[0]["credential"],
            credential,
        )
        self.assertEqual(
            validator.calls[0]["expected_ruc"],
            "80012345-6",
        )

    def test_missing_certificate_password_reference_is_not_ready(self):
        self._credential(password_secret_ref=False)
        validator = _CertificateValidationStub()

        report = self._service(validator).check(document=self.document)

        self.assertFalse(report["ready"])
        self.assertTrue(report["certificate_reference_configured"])
        self.assertFalse(report["certificate_password_configured"])
        self.assertEqual(
            report["status"],
            "certificate_password_missing",
        )
        self.assertEqual(validator.calls, [])

    def test_invalid_establishment_or_point_format_is_not_ready(self):
        service = self._service(_CertificateValidationStub())
        self.env.cr.execute(
            "UPDATE fiscal_py_establishment SET code = %s WHERE id = %s",
            ["01", self.establishment.id],
        )
        self.establishment.invalidate_recordset(["code"])

        establishment_report = service.check(document=self.document)

        self.assertEqual(
            establishment_report["status"],
            "fiscal_configuration_invalid",
        )
        self.assertIn(
            "three digits",
            " ".join(establishment_report["errors"]),
        )

        self.env.cr.execute(
            "UPDATE fiscal_py_establishment SET code = %s WHERE id = %s",
            ["001", self.establishment.id],
        )
        self.env.cr.execute(
            "UPDATE fiscal_py_point_of_issue SET code = %s WHERE id = %s",
            ["2A2", self.point.id],
        )
        self.establishment.invalidate_recordset(["code"])
        self.point.invalidate_recordset(["code"])

        point_report = service.check(document=self.document)

        self.assertEqual(
            point_report["status"],
            "fiscal_configuration_invalid",
        )
        self.assertIn(
            "three digits",
            " ".join(point_report["errors"]),
        )

    def _credential(
        self,
        *,
        password_secret_ref="env://SIFEN_TEST_P12_PASSWORD",
    ):
        credential = self.env["fiscal.credential"].create({
            "name": self.id(),
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "provider_type": "external_secret",
            "material_format": "pkcs12",
            "secret_ref": "file:///run/secrets/sifen/test-client.p12",
            "password_secret_ref": password_secret_ref,
        })
        for role in ("xml_signing", "mutual_tls"):
            self.env["fiscal.adapter.credential.binding"].create({
                "adapter_config_id": self.adapter.id,
                "credential_id": credential.id,
                "role": role,
            })
        return credential

    def _service(self, validator):
        return PySifenTestReadinessService(
            self.env,
            certificate_validation_service=validator,
        )
