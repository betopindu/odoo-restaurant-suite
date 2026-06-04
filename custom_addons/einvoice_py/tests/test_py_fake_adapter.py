import base64
import json

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_module.services.orchestrator import FiscalOrchestrator
from odoo.addons.einvoice_py.services.cdc_service import PyCdcService
from odoo.addons.einvoice_py.services.py_payload_builder import PyPayloadBuilder


class TestPyFakeAdapter(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "Py Fake Tenant",
            "code": "py-fake",
            "company_id": cls.env.company.id,
        })

    def _create_config(
        self,
        document_type="invoice",
        point_code="001",
        sequence_next_number=15,
        with_sequence=True,
        establishment=None,
        point_of_issue=None,
        issuer=None,
        issuer_ruc="80012345",
        issuer_ruc_dv="6",
        taxpayer_type="2",
    ):
        if not establishment:
            issuer = issuer or self.env["fiscal.py.issuer"].create({
                "name": f"Py Fake Issuer {point_code}",
                "tenant_id": self.tenant.id,
                "company_id": self.env.company.id,
                "environment": "test",
                "ruc": issuer_ruc,
                "ruc_dv": issuer_ruc_dv,
                "taxpayer_type": taxpayer_type,
            })
            establishment = self.env["fiscal.py.establishment"].create({
                "name": f"Main Establishment {point_code}",
                "code": "001",
                "tenant_id": self.tenant.id,
                "company_id": self.env.company.id,
                "issuer_id": issuer.id,
            })
        if not point_of_issue:
            point_of_issue = self.env["fiscal.py.point.of.issue"].create({
                "name": f"Point {point_code}",
                "code": point_code,
                "establishment_id": establishment.id,
            })
        timbrado = self.env["fiscal.py.timbrado"].create({
            "number": f"1234567{point_code[-1]}",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "environment": "test",
            "document_type": document_type,
            "allowed_point_of_issue_ids": [(6, 0, [point_of_issue.id])],
        })
        csc = self.env["fiscal.py.csc"].create({
            "name": f"Test CSC {point_code}",
            "id_csc": point_code,
            "csc_value": "test-csc-value",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "environment": "test",
        })
        sequence = self.env["fiscal.py.sequence"]
        if with_sequence:
            sequence = sequence.create({
                "name": f"Sequence {point_code} {document_type}",
                "tenant_id": self.tenant.id,
                "company_id": self.env.company.id,
                "timbrado_id": timbrado.id,
                "establishment_id": establishment.id,
                "point_of_issue_id": point_of_issue.id,
                "document_type": document_type,
                "next_number": sequence_next_number,
                "padding": 7,
            })
        return establishment, point_of_issue, timbrado, csc, sequence

    def _create_document(
        self,
        name="PY FAKE ACCEPT",
        document_type="invoice",
        issue_datetime="2026-06-04 12:00:00",
        extra_vals=None,
    ):
        vals = {
            "name": name,
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": document_type,
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Paraguay Test Customer",
            "issue_datetime": issue_datetime,
            "amount_total": 100,
            "line_ids": [
                (
                    0,
                    0,
                    {
                        "product_name": "Paraguay Test Item",
                        "quantity": 1,
                        "price_unit": 100,
                        "total": 100,
                    },
                ),
            ],
        }
        if extra_vals:
            vals.update(extra_vals)
        return self.env["fiscal.document"].create(vals)

    def _process(self, document):
        orchestrator = FiscalOrchestrator(self.env)
        orchestrator.mark_ready(document, actor_context={"actor_type": "system"})
        orchestrator.queue(document, actor_context={"actor_type": "system"})
        orchestrator.process_document(document, actor_context={"actor_type": "system"})

    def test_successful_py_processing(self):
        self._create_config()
        document = self._create_document()

        self._process(document)

        self.assertEqual(document.state, "accepted")
        self.assertEqual(document.authority_status, "accepted")
        self.assertEqual(document.country_identifier, document.py_cdc)

    def test_missing_config_moves_to_validation_error(self):
        document = self._create_document()

        self._process(document)

        self.assertEqual(document.state, "validation_error")
        self.assertFalse(document.transmission_ids)
        event = document.event_ids.filtered(
            lambda item: (
                item.event_type == "state_transition"
                and item.to_state == "validation_error"
            )
        )[-1:]
        self.assertTrue(event)
        self.assertIn("Active Paraguay point of issue is required.", event.message)
        self.assertIn("Active Paraguay issuer is required.", event.message)
        self.assertIn("Active Paraguay timbrado is required.", event.message)
        self.assertIn("Active Paraguay CSC is required.", event.message)

    def test_selected_paraguay_records_are_persisted(self):
        establishment, point_of_issue, timbrado, csc, sequence = self._create_config()
        document = self._create_document()

        self._process(document)

        self.assertEqual(document.py_establishment_id, establishment)
        self.assertEqual(document.py_point_of_issue_id, point_of_issue)
        self.assertEqual(document.py_timbrado_id, timbrado)
        self.assertEqual(document.py_csc_id, csc)

    def test_py_fake_persists_issuer_snapshot_fields(self):
        establishment, point_of_issue, timbrado, csc, sequence = self._create_config()
        issuer = establishment.issuer_id
        document = self._create_document()

        self._process(document)

        self.assertEqual(document.py_issuer_id, issuer)
        self.assertEqual(document.py_issuer_ruc, issuer.ruc)
        self.assertEqual(document.py_issuer_ruc_dv, issuer.ruc_dv)
        self.assertEqual(document.py_issuer_taxpayer_type, issuer.taxpayer_type)

    def test_sequence_assigns_number_and_increments_next_number(self):
        establishment, point_of_issue, timbrado, csc, sequence = self._create_config(
            sequence_next_number=15,
        )
        document = self._create_document()

        self._process(document)

        self.assertEqual(document.py_document_number, "0000015")
        self.assertEqual(document.py_full_number, "001-001-0000015")
        self.assertEqual(sequence.next_number, 16)

    def test_separate_points_of_issue_have_independent_sequences(self):
        establishment, first_point, first_timbrado, first_csc, first_sequence = self._create_config(
            point_code="001",
            sequence_next_number=15,
        )
        establishment, point_of_issue, timbrado, csc, sequence = self._create_config(
            point_code="003",
            sequence_next_number=1607535,
            establishment=establishment,
        )
        document = self._create_document()
        document.py_point_of_issue_id = point_of_issue

        self._process(document)

        self.assertEqual(document.py_document_number, "1607535")
        self.assertEqual(document.py_full_number, "001-003-1607535")
        self.assertEqual(sequence.next_number, 1607536)

    def test_different_document_type_has_independent_sequence(self):
        establishment, point_of_issue, first_timbrado, first_csc, first_sequence = self._create_config(
            document_type="invoice",
            sequence_next_number=15,
        )
        establishment, point_of_issue, timbrado, csc, sequence = self._create_config(
            document_type="credit_note",
            sequence_next_number=99,
            establishment=establishment,
            point_of_issue=point_of_issue,
        )
        document = self._create_document(document_type="credit_note")
        document.py_point_of_issue_id = point_of_issue

        self._process(document)

        self.assertEqual(document.py_document_number, "0000099")
        self.assertEqual(document.py_full_number, "001-001-0000099")
        self.assertEqual(sequence.next_number, 100)

    def test_retry_does_not_assign_new_number(self):
        establishment, point_of_issue, timbrado, csc, sequence = self._create_config(
            sequence_next_number=15,
        )
        document = self._create_document(name="PY FAKE RETRY")

        self._process(document)
        first_number = document.py_document_number
        first_full_number = document.py_full_number
        first_cod_seg = document.py_cod_seg
        first_cdc = document.py_cdc
        self.assertEqual(sequence.next_number, 16)

        FiscalOrchestrator(self.env).process_document(
            document,
            actor_context={"actor_type": "system"},
        )

        self.assertEqual(document.py_document_number, first_number)
        self.assertEqual(document.py_full_number, first_full_number)
        self.assertEqual(document.py_cod_seg, first_cod_seg)
        self.assertEqual(document.py_cdc, first_cdc)
        self.assertEqual(sequence.next_number, 16)

    def test_missing_sequence_moves_to_validation_error(self):
        self._create_config(with_sequence=False)
        document = self._create_document()

        self._process(document)

        self.assertEqual(document.state, "validation_error")
        event = document.event_ids.filtered(
            lambda item: (
                item.event_type == "state_transition"
                and item.to_state == "validation_error"
            )
        )[-1:]
        self.assertTrue(event)
        self.assertIn("Active Paraguay sequence is required.", event.message)

    def test_missing_issuer_moves_to_validation_error(self):
        establishment = self.env["fiscal.py.establishment"].create({
            "name": "Inactive Establishment Without Issuer",
            "code": "001",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "active": False,
        })
        point_of_issue = self.env["fiscal.py.point.of.issue"].create({
            "name": "Point Without Issuer",
            "code": "001",
            "establishment_id": establishment.id,
        })
        timbrado = self.env["fiscal.py.timbrado"].create({
            "number": "12345678",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "environment": "test",
            "document_type": "invoice",
            "allowed_point_of_issue_ids": [(6, 0, [point_of_issue.id])],
        })
        csc = self.env["fiscal.py.csc"].create({
            "name": "Test CSC Without Issuer",
            "id_csc": "001",
            "csc_value": "test-csc-value",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "environment": "test",
        })
        self.env["fiscal.py.sequence"].create({
            "name": "Sequence Without Issuer",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "timbrado_id": timbrado.id,
            "establishment_id": establishment.id,
            "point_of_issue_id": point_of_issue.id,
            "document_type": "invoice",
            "next_number": 15,
            "padding": 7,
        })
        document = self._create_document()

        self._process(document)

        self.assertEqual(document.state, "validation_error")
        event = document.event_ids.filtered(
            lambda item: (
                item.event_type == "state_transition"
                and item.to_state == "validation_error"
            )
        )[-1:]
        self.assertTrue(event)
        self.assertIn("Active Paraguay issuer is required.", event.message)

    def test_modulo_11_official_example(self):
        base = "0144444401700100100145282201701251587326098"

        digit, total, remainder = PyCdcService.calculate_check_digit(base)

        self.assertEqual(total, 773)
        self.assertEqual(remainder, 3)
        self.assertEqual(digit, 8)
        self.assertEqual(f"{base}{digit}", "01444444017001001001452822017012515873260988")

    def test_cdc_generated_from_official_example_inputs(self):
        self._create_config(
            sequence_next_number=14528,
            issuer_ruc="44444401",
            issuer_ruc_dv="7",
            taxpayer_type="2",
        )
        document = self._create_document(
            issue_datetime="2017-01-25 12:00:00",
            extra_vals={"py_cod_seg": "587326098"},
        )

        self._process(document)

        self.assertEqual(document.py_cdc_base, "0144444401700100100145282201701251587326098")
        self.assertEqual(document.py_cdc_dv, "8")
        self.assertEqual(document.py_cdc, "01444444017001001001452822017012515873260988")

    def test_cdc_lengths_and_country_identifier(self):
        self._create_config()
        document = self._create_document()

        self._process(document)

        self.assertEqual(len(document.py_cdc), 44)
        self.assertEqual(len(document.py_cdc_base), 43)
        self.assertEqual(len(document.py_cdc_dv), 1)
        self.assertEqual(len(document.py_cod_seg), 9)
        self.assertEqual(document.country_identifier, document.py_cdc)

    def test_unsupported_document_type_moves_to_validation_error(self):
        self._create_config()
        document = self._create_document(document_type="receipt")

        self._process(document)

        self.assertEqual(document.state, "validation_error")
        event = document.event_ids.filtered(
            lambda item: (
                item.event_type == "state_transition"
                and item.to_state == "validation_error"
            )
        )[-1:]
        self.assertTrue(event)
        self.assertIn("Unsupported Paraguay CDC document type: receipt.", event.message)

    def test_missing_cdc_required_input_moves_to_validation_error(self):
        self._create_config()
        document = self._create_document(issue_datetime=False)

        self._process(document)

        self.assertEqual(document.state, "validation_error")
        event = document.event_ids.filtered(
            lambda item: (
                item.event_type == "state_transition"
                and item.to_state == "validation_error"
            )
        )[-1:]
        self.assertTrue(event)
        self.assertIn("Paraguay CDC issue datetime is required.", event.message)

    def test_payload_builder_returns_expected_main_sections(self):
        self._create_config()
        document = self._create_document()
        self._process(document)

        payload = PyPayloadBuilder(self.env).build(document)

        self.assertEqual(
            set(payload),
            {
                "version",
                "cdc",
                "document",
                "operation",
                "issuer",
                "receiver",
                "condition",
                "items",
                "totals",
                "paraguay",
                "warnings",
            },
        )
        self.assertEqual(payload["version"], "150")
        self.assertEqual(payload["cdc"], document.py_cdc)
        self.assertEqual(payload["document"]["py_i_tide"], "01")
        self.assertEqual(payload["issuer"]["ruc"], document.py_issuer_ruc)
        self.assertEqual(payload["items"][0]["description"], "Paraguay Test Item")

    def test_payload_builder_missing_cdc_fails(self):
        self._create_config()
        document = self._create_document()

        with self.assertRaises(ValidationError):
            PyPayloadBuilder(self.env).build(document)

    def test_payload_builder_returns_warnings_for_defaults_and_missing_optional_fields(self):
        self._create_config()
        document = self._create_document()
        self._process(document)

        payload = PyPayloadBuilder(self.env).build(document)

        self.assertIn("Defaulted transaction type for Paraguay payload.", payload["warnings"])
        self.assertIn("Receiver RUC/document DV is missing.", payload["warnings"])
        self.assertIn("Receiver email is missing.", payload["warnings"])
        self.assertIn("Detailed Paraguay tax buckets are not fully modeled yet.", payload["warnings"])

    def test_payload_attachment_created_during_py_fake_processing(self):
        self._create_config()
        document = self._create_document()

        self._process(document)

        attachment = self.env["fiscal.attachment"].search([
            ("document_id", "=", document.id),
            ("attachment_type", "=", "paraguay_payload_json"),
        ])
        self.assertEqual(len(attachment), 1)
        self.assertEqual(attachment.mimetype, "application/json")
        self.assertTrue(attachment.sha256)
        self.assertTrue(attachment.ir_attachment_id)
        self.assertTrue(attachment.is_sensitive)
        content = base64.b64decode(attachment.ir_attachment_id.datas)
        payload = json.loads(content.decode("utf-8"))
        self.assertEqual(payload["cdc"], document.py_cdc)

    def test_retry_does_not_duplicate_payload_attachment(self):
        self._create_config()
        document = self._create_document(name="PY FAKE RETRY")

        self._process(document)
        attachments = self.env["fiscal.attachment"].search([
            ("document_id", "=", document.id),
            ("attachment_type", "=", "paraguay_payload_json"),
        ])
        self.assertEqual(len(attachments), 1)

        FiscalOrchestrator(self.env).process_document(
            document,
            actor_context={"actor_type": "system"},
        )

        attachments = self.env["fiscal.attachment"].search([
            ("document_id", "=", document.id),
            ("attachment_type", "=", "paraguay_payload_json"),
        ])
        self.assertEqual(len(attachments), 1)
