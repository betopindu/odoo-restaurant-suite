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

        self.assertIn("Receiver RUC/document DV is missing.", payload["warnings"])
        self.assertIn("Receiver email is missing.", payload["warnings"])
        self.assertIn("Receiver nature is missing.", payload["warnings"])
        self.assertIn("Line 10: tax affectation is missing.", payload["warnings"])

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

    def _enrich_document_for_payload(self, document):
        document.write({
            "customer_tax_id": "1234567-8",
            "customer_email": "customer@example.com",
            "py_receiver_nature": "1",
            "py_receiver_operation_type": "1",
            "py_receiver_country_code": "PRY",
            "py_receiver_address": "Test receiver address",
            "py_receiver_phone": "0981000000",
            "py_transaction_type_code": "1",
            "py_tax_type_code": "1",
            "py_currency": "PYG",
            "py_sale_condition_code": "2",
            "py_payment_type_code": "5",
            "py_payment_amount": 100,
            "py_payment_currency": "PYG",
        })
        document.line_ids.write({
            "py_internal_code": "ITEM-001",
            "py_unit_measure_code": "77",
            "py_unit_measure_description": "UNI",
            "py_tax_affectation": "1",
            "py_tax_rate": 10,
            "py_tax_base": 90.91,
            "py_tax_amount": 9.09,
            "py_discount_amount": 0,
        })

    def test_payload_uses_explicit_receiver_fields(self):
        self._create_config()
        document = self._create_document()
        self._enrich_document_for_payload(document)
        self._process(document)

        payload = PyPayloadBuilder(self.env).build(document)

        self.assertEqual(payload["receiver"]["ruc_or_document"], "1234567")
        self.assertEqual(payload["receiver"]["ruc_dv"], "8")
        self.assertEqual(payload["receiver"]["email"], "customer@example.com")
        self.assertEqual(payload["receiver"]["address"], "Test receiver address")
        self.assertEqual(payload["receiver"]["phone"], "0981000000")
        self.assertEqual(payload["receiver"]["nature_code"], "1")
        self.assertEqual(payload["receiver"]["type_code"], "1")

    def test_payload_uses_explicit_payment_fields(self):
        self._create_config()
        document = self._create_document()
        self._enrich_document_for_payload(document)
        self._process(document)

        payload = PyPayloadBuilder(self.env).build(document)

        self.assertEqual(payload["condition"]["sale_condition_code"], "2")
        self.assertEqual(payload["condition"]["payment_type_code"], "5")
        self.assertEqual(payload["condition"]["payment_amount"], 100)
        self.assertEqual(payload["condition"]["payment_currency"], "PYG")

    def test_payload_uses_explicit_operation_fields(self):
        self._create_config()
        document = self._create_document()
        self._enrich_document_for_payload(document)
        self._process(document)

        payload = PyPayloadBuilder(self.env).build(document)

        self.assertEqual(payload["operation"]["transaction_type_code"], "1")
        self.assertEqual(payload["operation"]["tax_type_code"], "1")
        self.assertEqual(payload["operation"]["currency"], "PYG")

    def test_payload_uses_explicit_item_tax_fields(self):
        self._create_config()
        document = self._create_document()
        self._enrich_document_for_payload(document)
        self._process(document)

        payload = PyPayloadBuilder(self.env).build(document)
        item = payload["items"][0]

        self.assertEqual(item["code"], "ITEM-001")
        self.assertEqual(item["unit_measure_code"], "77")
        self.assertEqual(item["tax_affectation"], "1")
        self.assertEqual(item["tax_rate"], 10)
        self.assertEqual(item["tax_base"], 90.91)
        self.assertEqual(item["tax_amount"], 9.09)

    def test_tax_buckets_for_exempt_line(self):
        self._create_config()
        document = self._create_document()
        self._enrich_document_for_payload(document)
        document.line_ids.write({
            "py_tax_affectation": "3",
            "py_tax_rate": 0,
            "py_tax_base": 0,
            "py_tax_amount": 0,
            "py_exempt_base": 100,
        })
        self._process(document)

        totals = PyPayloadBuilder(self.env).build(document)["totals"]

        self.assertEqual(totals["subtotal_exempt"], 100)
        self.assertEqual(totals["subtotal_5"], 0)
        self.assertEqual(totals["subtotal_10"], 0)
        self.assertEqual(totals["total_vat"], 0)

    def test_tax_buckets_for_iva_5_line(self):
        self._create_config()
        document = self._create_document()
        self._enrich_document_for_payload(document)
        document.line_ids.write({
            "py_tax_affectation": "1",
            "py_tax_rate": 5,
            "py_tax_base": 95.24,
            "py_tax_amount": 4.76,
        })
        self._process(document)

        totals = PyPayloadBuilder(self.env).build(document)["totals"]

        self.assertEqual(totals["subtotal_5"], 95.24)
        self.assertEqual(totals["total_vat_5"], 4.76)
        self.assertEqual(totals["total_vat"], 4.76)

    def test_tax_buckets_for_iva_10_line(self):
        self._create_config()
        document = self._create_document()
        self._enrich_document_for_payload(document)
        self._process(document)

        totals = PyPayloadBuilder(self.env).build(document)["totals"]

        self.assertEqual(totals["subtotal_10"], 90.91)
        self.assertEqual(totals["total_vat_10"], 9.09)
        self.assertEqual(totals["total_vat"], 9.09)

    def test_warnings_are_reduced_when_explicit_fields_are_populated(self):
        self._create_config()
        minimal_document = self._create_document()
        self._process(minimal_document)
        minimal_warnings = PyPayloadBuilder(self.env).build(minimal_document)["warnings"]

        self._create_config(
            point_code="002",
            establishment=minimal_document.py_establishment_id,
        )
        enriched_document = self._create_document()
        enriched_document.py_point_of_issue_id = self.env["fiscal.py.point.of.issue"].search(
            [("code", "=", "002")],
            order="id desc",
            limit=1,
        )
        self._enrich_document_for_payload(enriched_document)
        self._process(enriched_document)
        enriched_warnings = PyPayloadBuilder(self.env).build(enriched_document)["warnings"]

        self.assertLess(len(enriched_warnings), len(minimal_warnings))
        self.assertNotIn("Receiver email is missing.", enriched_warnings)
        self.assertNotIn("Receiver nature is missing.", enriched_warnings)
        self.assertNotIn("Line 10: tax affectation is missing.", enriched_warnings)
