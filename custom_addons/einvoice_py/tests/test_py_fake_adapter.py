import base64
from copy import deepcopy
import json
from xml.etree import ElementTree as ET

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_module.services.orchestrator import FiscalOrchestrator
from odoo.addons.einvoice_py.services.cdc_service import PyCdcService
from odoo.addons.einvoice_py.services.py_payload_builder import PyPayloadBuilder
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import PyUnsignedXmlBuilder
from odoo.addons.einvoice_py.services.py_xml_validation_service import PyXmlValidationService


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
        schema_ready=True,
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
            if schema_ready and not issuer.economic_activity_ids:
                self.env["fiscal.py.economic.activity"].create({
                    "issuer_id": issuer.id,
                    "code": "620100",
                    "description": "DESARROLLO DE SOFTWARE",
                    "sequence": 10,
                })
            establishment = self.env["fiscal.py.establishment"].create({
                "name": f"Main Establishment {point_code}",
                "code": "001",
                "tenant_id": self.tenant.id,
                "company_id": self.env.company.id,
                "issuer_id": issuer.id,
                "house_number": "123",
                "department_code": "1",
                "department_name": "CAPITAL",
                "district_code": "1",
                "district_name": "ASUNCION",
                "city_code": "1",
                "city_name": "ASUNCION",
                "branch_name": "CASA MATRIZ",
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
                "environment",
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

    def test_incomplete_debug_payload_processing_skips_unsigned_xml(self):
        self._create_config()
        document = self._create_document()

        self._process(document)

        payload_attachment = self.env["fiscal.attachment"].search([
            ("document_id", "=", document.id),
            ("attachment_type", "=", "paraguay_payload_json"),
        ])
        self.assertEqual(document.state, "accepted")
        self.assertEqual(len(payload_attachment), 1)
        self.assertFalse(self._xml_attachment(document))

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
            "py_receiver_taxpayer_type": "1",
            "py_receiver_operation_type": "1",
            "py_receiver_country_code": "PRY",
            "py_receiver_country_description": "Paraguay",
            "py_receiver_address": "Test receiver address",
            "py_receiver_house_number": "456",
            "py_receiver_phone": "0981000000",
            "py_receiver_department_code": "1",
            "py_receiver_department_name": "CAPITAL",
            "py_receiver_district_code": "1",
            "py_receiver_district_name": "ASUNCION",
            "py_receiver_city_code": "1",
            "py_receiver_city_name": "ASUNCION",
            "py_receiver_customer_code": "CUST-001",
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

    def _enrich_standard_cash_invoice(self, document):
        self._enrich_document_for_payload(document)
        document.write({
            "py_transaction_type_code": "2",
            "py_sale_condition_code": "1",
            "py_payment_type_code": "1",
            "py_payment_amount": 100,
            "py_payment_currency": "PYG",
        })

    def _xml_attachment(self, document):
        return self.env["fiscal.attachment"].search([
            ("document_id", "=", document.id),
            ("attachment_type", "=", "paraguay_xml_unsigned"),
        ])

    def _xml_root_from_attachment(self, attachment):
        content = base64.b64decode(attachment.ir_attachment_id.datas)
        return ET.fromstring(content)

    def _xml_path(self, path):
        namespace = PyUnsignedXmlBuilder.SIFEN_NS
        return "/".join(f"{{{namespace}}}{part}" for part in path.split("/"))

    def _xml_find(self, root, path):
        return root.find(self._xml_path(path))

    def _xml_findtext(self, root, path):
        return root.findtext(self._xml_path(path))

    def _payload_for_xml(self, document):
        if not document.py_cdc:
            self._process(document)
        return PyPayloadBuilder(self.env).build(document)

    def _xml_bytes_for_document(self, document):
        return base64.b64decode(self._xml_attachment(document).ir_attachment_id.datas)

    def _xml_bytes_from_root(self, root):
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

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
        self.assertEqual(payload["receiver"]["country_description"], "Paraguay")
        self.assertEqual(payload["receiver"]["nature_code"], "1")
        self.assertEqual(payload["receiver"]["taxpayer_type"], "1")
        self.assertEqual(payload["receiver"]["type_code"], "1")
        self.assertEqual(payload["receiver"]["type_description"], "B2B")
        self.assertEqual(payload["receiver"]["house_number"], "456")
        self.assertEqual(payload["receiver"]["department_code"], "1")
        self.assertEqual(payload["receiver"]["department_name"], "CAPITAL")
        self.assertEqual(payload["receiver"]["district_code"], "1")
        self.assertEqual(payload["receiver"]["district_name"], "ASUNCION")
        self.assertEqual(payload["receiver"]["city_code"], "1")
        self.assertEqual(payload["receiver"]["city_name"], "ASUNCION")
        self.assertEqual(payload["receiver"]["customer_code"], "CUST-001")

    def test_payload_uses_issuer_schema_readiness_fields(self):
        establishment, point_of_issue, timbrado, csc, sequence = self._create_config()
        timbrado.write({
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
        })
        issuer = establishment.issuer_id
        self.env["fiscal.py.economic.activity"].create({
            "issuer_id": issuer.id,
            "code": "471100",
            "description": "COMERCIO AL POR MENOR",
            "sequence": 5,
        })
        self.env["fiscal.py.economic.activity"].create({
            "issuer_id": issuer.id,
            "code": "999999",
            "description": "INACTIVE ACTIVITY",
            "sequence": 1,
            "active": False,
        })
        document = self._create_document()
        self._enrich_document_for_payload(document)
        self._process(document)

        issuer_payload = PyPayloadBuilder(self.env).build(document)["issuer"]

        self.assertEqual(issuer_payload["house_number"], "123")
        self.assertEqual(issuer_payload["department_code"], "1")
        self.assertEqual(issuer_payload["department_name"], "CAPITAL")
        self.assertEqual(issuer_payload["district_code"], "1")
        self.assertEqual(issuer_payload["district_name"], "ASUNCION")
        self.assertEqual(issuer_payload["city_code"], "1")
        self.assertEqual(issuer_payload["city_name"], "ASUNCION")
        self.assertEqual(issuer_payload["branch_name"], "CASA MATRIZ")
        self.assertEqual(issuer_payload["timbrado_valid_from"], "2026-01-01")
        self.assertEqual(issuer_payload["timbrado_valid_to"], "2026-12-31")
        self.assertEqual(
            issuer_payload["economic_activities"],
            [
                {
                    "code": "471100",
                    "description": "COMERCIO AL POR MENOR",
                },
                {
                    "code": "620100",
                    "description": "DESARROLLO DE SOFTWARE",
                },
            ],
        )

    def test_payload_uses_non_taxpayer_receiver_identity_fields(self):
        self._create_config()
        document = self._create_document()
        self._enrich_document_for_payload(document)
        document.write({
            "py_receiver_nature": "2",
            "py_receiver_taxpayer_type": False,
            "py_receiver_id_type": "1",
            "py_receiver_id_type_description": "Cedula paraguaya",
            "py_receiver_id_number": "1234567",
        })
        self._process(document)

        receiver = PyPayloadBuilder(self.env).build(document)["receiver"]

        self.assertEqual(receiver["nature_code"], "2")
        self.assertFalse(receiver["taxpayer_type"])
        self.assertEqual(receiver["id_type"], "1")
        self.assertEqual(receiver["id_type_description"], "Cedula paraguaya")
        self.assertEqual(receiver["id_number"], "1234567")

    def test_payload_receiver_operation_type_mapping_is_sifen_aligned(self):
        self._create_config()
        document = self._create_document()
        self._enrich_document_for_payload(document)
        document.write({"py_receiver_operation_type": "4"})
        self._process(document)

        receiver = PyPayloadBuilder(self.env).build(document)["receiver"]

        self.assertEqual(receiver["type_code"], "4")
        self.assertEqual(receiver["type_description"], "B2F")

        document.write({"py_receiver_operation_type": "3"})
        receiver = PyPayloadBuilder(self.env).build(document)["receiver"]
        self.assertEqual(receiver["type_code"], "3")
        self.assertEqual(receiver["type_description"], "B2G")
        self.assertNotEqual(receiver["type_description"], "Foreign")

    def test_missing_schema_readiness_fields_warn_without_blocking_payload(self):
        establishment, point_of_issue, timbrado, csc, sequence = self._create_config()
        establishment.write({
            "house_number": False,
            "department_code": False,
            "department_name": False,
            "district_code": False,
            "district_name": False,
            "city_code": False,
            "city_name": False,
            "branch_name": False,
        })
        establishment.issuer_id.economic_activity_ids.write({"active": False})
        document = self._create_document()
        self._enrich_document_for_payload(document)
        document.write({
            "py_receiver_country_description": False,
            "py_receiver_taxpayer_type": False,
            "py_receiver_house_number": False,
            "py_receiver_department_code": False,
            "py_receiver_department_name": False,
            "py_receiver_district_code": False,
            "py_receiver_district_name": False,
            "py_receiver_city_code": False,
            "py_receiver_city_name": False,
        })
        self._process(document)

        payload = PyPayloadBuilder(self.env).build(document)

        self.assertEqual(payload["cdc"], document.py_cdc)
        self.assertIn("Issuer establishment house number is missing.", payload["warnings"])
        self.assertIn("Issuer establishment department code is missing.", payload["warnings"])
        self.assertIn("Issuer economic activities are missing.", payload["warnings"])
        self.assertIn("Receiver country description is missing.", payload["warnings"])
        self.assertIn("Receiver taxpayer type is missing.", payload["warnings"])
        self.assertIn("Receiver house number is missing.", payload["warnings"])
        self.assertIn("Receiver city name is missing.", payload["warnings"])

    def test_payload_uses_explicit_payment_fields(self):
        self._create_config()
        document = self._create_document()
        self._enrich_document_for_payload(document)
        self._process(document)

        payload = PyPayloadBuilder(self.env).build(document)

        self.assertEqual(payload["condition"]["sale_condition_code"], "2")
        self.assertEqual(payload["condition"]["sale_condition_description"], "Crédito")
        self.assertEqual(payload["condition"]["payment_type_code"], "5")
        self.assertEqual(payload["condition"]["payment_type_description"], "Transferencia bancaria")
        self.assertEqual(payload["condition"]["payment_amount"], 100)
        self.assertEqual(payload["condition"]["payment_currency"], "PYG")
        self.assertEqual(payload["condition"]["payment_currency_description"], "Guarani")

    def test_payload_uses_explicit_operation_fields(self):
        self._create_config()
        document = self._create_document()
        self._enrich_document_for_payload(document)
        self._process(document)

        payload = PyPayloadBuilder(self.env).build(document)

        self.assertEqual(payload["operation"]["transaction_type_code"], "1")
        self.assertEqual(payload["operation"]["transaction_type_description"], "Venta de mercadería")
        self.assertEqual(payload["operation"]["tax_type_code"], "1")
        self.assertEqual(payload["operation"]["tax_type_description"], "IVA")
        self.assertEqual(payload["operation"]["currency"], "PYG")
        self.assertEqual(payload["operation"]["currency_description"], "Guarani")

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
        self.assertEqual(item["tax_affectation_description"], "Gravado IVA")
        self.assertEqual(item["tax_rate"], 10)
        self.assertEqual(item["tax_base"], 90.90909091)
        self.assertEqual(item["tax_amount"], 9.09090909)
        self.assertEqual(item["discount_percent"], 0)
        self.assertEqual(item["global_discount"], 0)
        self.assertEqual(item["unit_advance"], 0)
        self.assertEqual(item["global_advance"], 0)

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

        self.assertEqual(totals["subtotal_5"], 100)
        self.assertEqual(totals["base_5"], 95.23809524)
        self.assertEqual(totals["total_vat_5"], 4.76190476)
        self.assertEqual(totals["total_vat"], 4.76190476)

    def test_tax_buckets_for_iva_10_line(self):
        self._create_config()
        document = self._create_document()
        self._enrich_document_for_payload(document)
        self._process(document)

        totals = PyPayloadBuilder(self.env).build(document)["totals"]

        self.assertEqual(totals["subtotal_10"], 100)
        self.assertEqual(totals["base_10"], 90.90909091)
        self.assertEqual(totals["total_vat_10"], 9.09090909)
        self.assertEqual(totals["total_vat"], 9.09090909)

    def test_standard_cash_taxpayer_invoice_generates_clean_payload(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)

        self._process(document)

        attachment = self.env["fiscal.attachment"].search([
            ("document_id", "=", document.id),
            ("attachment_type", "=", "paraguay_payload_json"),
        ])
        self.assertEqual(len(attachment), 1)
        payload = json.loads(base64.b64decode(attachment.ir_attachment_id.datas).decode("utf-8"))
        self.assertEqual(document.state, "accepted")
        self.assertTrue(document.py_full_number)
        self.assertEqual(len(document.py_cdc), 44)
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(payload["condition"]["sale_condition_code"], "1")
        self.assertEqual(payload["condition"]["payment_type_code"], "1")
        self.assertEqual(payload["receiver"]["nature_code"], "1")
        self.assertEqual(payload["receiver"]["type_code"], "1")
        self.assertEqual(payload["totals"]["subtotal_10"], 100)
        self.assertEqual(payload["totals"]["base_10"], 90.90909091)
        self.assertEqual(payload["totals"]["total_vat_10"], 9.09090909)

    def test_unsigned_xml_can_be_parsed_and_has_key_groups(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)

        attachment = self._xml_attachment(document)
        self.assertEqual(len(attachment), 1)
        root = self._xml_root_from_attachment(attachment)

        self.assertEqual(root.tag, self._xml_path("rDE"))
        self.assertNotIn("version", root.attrib)
        self.assertEqual(
            root.attrib[f"{{{PyUnsignedXmlBuilder.XSI_NS}}}schemaLocation"],
            PyUnsignedXmlBuilder.SCHEMA_LOCATION,
        )
        self.assertIsNotNone(self._xml_find(root, "DE/gOpeDE"))
        self.assertIsNotNone(self._xml_find(root, "DE/gTimb"))
        self.assertIsNotNone(self._xml_find(root, "DE/gDatGralOpe"))
        self.assertIsNotNone(self._xml_find(root, "DE/gDatGralOpe/gOpeCom"))
        self.assertIsNotNone(self._xml_find(root, "DE/gDatGralOpe/gEmis"))
        self.assertIsNotNone(self._xml_find(root, "DE/gDatGralOpe/gDatRec"))
        self.assertIsNotNone(self._xml_find(root, "DE/gDtipDE"))
        self.assertIsNotNone(self._xml_find(root, "DE/gTotSub"))

    def test_unsigned_xml_contains_expected_values(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)

        root = self._xml_root_from_attachment(self._xml_attachment(document))
        de = self._xml_find(root, "DE")

        self.assertEqual(de.attrib["Id"], document.py_cdc)
        self.assertEqual(self._xml_findtext(root, "DE/dDVId"), document.py_cdc_dv)
        self.assertEqual(self._xml_findtext(root, "DE/dSisFact"), "1")
        self.assertIsNone(self._xml_find(root, "DE/dFecFirma"))
        self.assertEqual(self._xml_findtext(root, "DE/gOpeDE/iTipEmi"), "1")
        self.assertEqual(self._xml_findtext(root, "DE/gOpeDE/dDesTipEmi"), "Normal")
        self.assertEqual(self._xml_findtext(root, "DE/gOpeDE/dCodSeg"), document.py_cod_seg)
        self.assertIsNone(self._xml_find(root, "DE/gDatGralOpe/iTipEmi"))
        self.assertIsNone(self._xml_find(root, "DE/gDatGralOpe/dCodSeg"))
        self.assertEqual(self._xml_findtext(root, "DE/gTimb/iTiDE"), "1")
        self.assertEqual(self._xml_findtext(root, "DE/gTimb/dDesTiDE"), "Factura electrónica")
        self.assertEqual(
            self._xml_findtext(root, "DE/gTimb/dNumTim"),
            document.py_timbrado_id.number.zfill(8),
        )
        self.assertEqual(self._xml_findtext(root, "DE/gTimb/dEst"), "001")
        self.assertEqual(self._xml_findtext(root, "DE/gTimb/dPunExp"), "001")
        self.assertEqual(self._xml_findtext(root, "DE/gTimb/dNumDoc"), "0000015")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gEmis/dRucEm"), document.py_issuer_ruc)
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gEmis/dDVEmi"), document.py_issuer_ruc_dv)
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gEmis/dNumCas"), "123")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gEmis/cDepEmi"), "1")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gEmis/dDesDepEmi"), "CAPITAL")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gEmis/cDisEmi"), "1")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gEmis/dDesDisEmi"), "ASUNCION")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gEmis/cCiuEmi"), "1")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gEmis/dDesCiuEmi"), "ASUNCION")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gEmis/dDenSuc"), "CASA MATRIZ")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/dNomRec"), document.customer_name)
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/iTiContRec"), "1")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/dRucRec"), "1234567")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/dDVRec"), "8")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/dDesPaisRe"), "Paraguay")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/dNumCasRec"), "456")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/cDepRec"), "1")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/dDesDepRec"), "CAPITAL")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/cDisRec"), "1")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/dDesDisRec"), "ASUNCION")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/cCiuRec"), "1")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/dDesCiuRec"), "ASUNCION")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/dCodCliente"), "CUST-001")
        self.assertEqual(
            self._xml_findtext(root, "DE/gDatGralOpe/gOpeCom/dDesTipTra"),
            "Prestación de servicios",
        )
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gOpeCom/dDesTImp"), "IVA")
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gOpeCom/dDesMoneOpe"), "Guarani")
        self.assertEqual(self._xml_findtext(root, "DE/gDtipDE/gCamFE/iIndPres"), "1")
        self.assertEqual(self._xml_findtext(root, "DE/gDtipDE/gCamCond/dDCondOpe"), "Contado")
        self.assertEqual(
            self._xml_findtext(root, "DE/gDtipDE/gCamCond/gPaConEIni/dDesTiPag"),
            "Efectivo",
        )
        self.assertEqual(
            self._xml_findtext(root, "DE/gDtipDE/gCamCond/gPaConEIni/dDMoneTiPag"),
            "Guarani",
        )
        self.assertEqual(self._xml_findtext(root, "DE/gDtipDE/gCamItem/dDesProSer"), "Paraguay Test Item")
        self.assertEqual(
            self._xml_findtext(root, "DE/gDtipDE/gCamItem/gValorItem/gValorRestaItem/dTotOpeItem"),
            "100.00000000",
        )
        self.assertEqual(
            self._xml_findtext(root, "DE/gDtipDE/gCamItem/gValorItem/gValorRestaItem/dPorcDesIt"),
            "0.00000000",
        )
        self.assertEqual(
            self._xml_findtext(root, "DE/gDtipDE/gCamItem/gValorItem/gValorRestaItem/dDescGloItem"),
            "0.00000000",
        )
        self.assertEqual(
            self._xml_findtext(root, "DE/gDtipDE/gCamItem/gValorItem/gValorRestaItem/dAntPreUniIt"),
            "0.00000000",
        )
        self.assertEqual(
            self._xml_findtext(root, "DE/gDtipDE/gCamItem/gValorItem/gValorRestaItem/dAntGloPreUniIt"),
            "0.00000000",
        )
        self.assertEqual(float(self._xml_findtext(root, "DE/gDtipDE/gCamItem/gCamIVA/dTasaIVA")), 10.0)
        self.assertEqual(
            self._xml_findtext(root, "DE/gDtipDE/gCamItem/gCamIVA/dDesAfecIVA"),
            "Gravado IVA",
        )
        self.assertEqual(self._xml_findtext(root, "DE/gTotSub/dIVA10"), "9.09090909")
        self.assertIsNone(self._xml_find(root, "DE/gTotSub/dTotIVA10"))
        self.assertIsNone(self._xml_find(root, "DE/gTotSub/dTotIVA5"))
        self.assertEqual(self._xml_findtext(root, "DE/gTotSub/dSub10"), "100.00000000")
        self.assertEqual(self._xml_findtext(root, "DE/gTotSub/dBaseGrav10"), "90.90909091")
        self.assertEqual(self._xml_findtext(root, "DE/gTotSub/dTBasGraIVA"), "90.90909091")

    def test_sifen_v150_iva_inclusive_totals_use_item_total_not_tax_base(self):
        self._create_config()
        document = self._create_document(extra_vals={
            "amount_untaxed": 100000,
            "amount_tax": 10000,
            "amount_total": 110000,
        })
        self._enrich_standard_cash_invoice(document)
        document.write({"py_payment_amount": 110000})
        document.line_ids.write({
            "quantity": 1,
            "price_unit": 110000,
            "subtotal": 100000,
            "total": 110000,
            "py_tax_affectation": "1",
            "py_tax_rate": 10,
            "py_tax_proportion": 100,
        })
        self._process(document)

        payload = PyPayloadBuilder(self.env).build(document)
        xml = PyUnsignedXmlBuilder(self.env).build_from_payload(payload)
        root = ET.fromstring(xml)

        self.assertEqual(payload["items"][0]["gross_total"], 110000)
        self.assertEqual(payload["items"][0]["tax_base"], 100000)
        self.assertEqual(payload["items"][0]["tax_amount"], 10000)
        self.assertEqual(payload["totals"]["subtotal_10"], 110000)
        self.assertEqual(payload["totals"]["base_10"], 100000)
        self.assertEqual(self._xml_findtext(root, "DE/gTotSub/dSub10"), "110000.00000000")
        self.assertEqual(self._xml_findtext(root, "DE/gTotSub/dBaseGrav10"), "100000.00000000")

    def test_sifen_v150_decimal_quantity_discount_and_rounding_are_consistent(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        document.line_ids.write({
            "quantity": 1.5,
            "price_unit": 123.456789,
            "py_discount_amount": 3.456789,
            "py_tax_affectation": "1",
            "py_tax_rate": 5,
            "py_tax_proportion": 100,
        })
        self._process(document)

        payload = PyPayloadBuilder(self.env).build(document)
        item = payload["items"][0]
        totals = payload["totals"]

        self.assertEqual(item["gross_total"], 185.19)
        self.assertEqual(item["total"], 180.0048165)
        self.assertEqual(item["tax_base"], 171.43315857)
        self.assertEqual(item["tax_amount"], 8.57165793)
        self.assertEqual(totals["subtotal_5"], item["total"])
        self.assertEqual(totals["base_5"], item["tax_base"])
        self.assertEqual(totals["total_vat_5"], item["tax_amount"])
        self.assertEqual(totals["total_operation"], totals["total_general"])

    def test_unsigned_xml_emits_repeated_economic_activities_in_payload_order(self):
        establishment, point_of_issue, timbrado, csc, sequence = self._create_config()
        self.env["fiscal.py.economic.activity"].create({
            "issuer_id": establishment.issuer_id.id,
            "code": "471100",
            "description": "COMERCIO AL POR MENOR",
            "sequence": 5,
        })
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)

        root = self._xml_root_from_attachment(self._xml_attachment(document))
        activities = self._xml_find(root, "DE/gDatGralOpe/gEmis").findall(
            self._xml_path("gActEco")
        )

        self.assertEqual(len(activities), 2)
        self.assertEqual(activities[0].findtext(self._xml_path("cActEco")), "471100")
        self.assertEqual(
            activities[0].findtext(self._xml_path("dDesActEco")),
            "COMERCIO AL POR MENOR",
        )
        self.assertEqual(activities[1].findtext(self._xml_path("cActEco")), "620100")
        self.assertEqual(
            activities[1].findtext(self._xml_path("dDesActEco")),
            "DESARROLLO DE SOFTWARE",
        )

    def test_unsigned_xml_emits_non_taxpayer_receiver_identity_only(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        document.write({
            "customer_tax_id": False,
            "py_receiver_nature": "2",
            "py_receiver_taxpayer_type": False,
            "py_receiver_id_type": "1",
            "py_receiver_id_type_description": "Cedula paraguaya",
            "py_receiver_id_number": "1234567",
        })
        self._process(document)

        root = self._xml_root_from_attachment(self._xml_attachment(document))
        receiver = self._xml_find(root, "DE/gDatGralOpe/gDatRec")

        self.assertEqual(receiver.findtext(self._xml_path("iNatRec")), "2")
        self.assertEqual(receiver.findtext(self._xml_path("iTipIDRec")), "1")
        self.assertEqual(receiver.findtext(self._xml_path("dDTipIDRec")), "Cedula paraguaya")
        self.assertEqual(receiver.findtext(self._xml_path("dNumIDRec")), "1234567")
        self.assertIsNone(receiver.find(self._xml_path("iTiContRec")))
        self.assertIsNone(receiver.find(self._xml_path("dRucRec")))
        self.assertIsNone(receiver.find(self._xml_path("dDVRec")))

    def test_unsigned_xml_receiver_operation_type_b2g_b2f(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        document.write({"py_receiver_operation_type": "3"})
        payload = self._payload_for_xml(document)
        xml_bytes = PyUnsignedXmlBuilder(self.env).build_from_payload(payload)
        root = ET.fromstring(xml_bytes)

        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/iTiOpe"), "3")

        payload["receiver"]["type_code"] = "4"
        xml_bytes = PyUnsignedXmlBuilder(self.env).build_from_payload(payload)
        root = ET.fromstring(xml_bytes)
        self.assertEqual(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/iTiOpe"), "4")

    def test_unsigned_xml_gcamiva_child_order_is_schema_ready(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)

        root = self._xml_root_from_attachment(self._xml_attachment(document))
        tax = self._xml_find(root, "DE/gDtipDE/gCamItem/gCamIVA")
        namespace = PyUnsignedXmlBuilder.SIFEN_NS
        names = [child.tag.replace(f"{{{namespace}}}", "") for child in tax]

        self.assertEqual(
            names,
            [
                "iAfecIVA",
                "dDesAfecIVA",
                "dPropIVA",
                "dTasaIVA",
                "dBasGravIVA",
                "dLiqIVAItem",
                "dBasExe",
            ],
        )

    def test_unsigned_xml_repeated_item_count_is_correct(self):
        self._create_config()
        document = self._create_document(
            extra_vals={
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_name": "Item A",
                            "quantity": 1,
                            "price_unit": 100,
                            "total": 100,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "product_name": "Item B",
                            "quantity": 2,
                            "price_unit": 50,
                            "total": 100,
                        },
                    ),
                ],
                "amount_total": 200,
            },
        )
        self._enrich_standard_cash_invoice(document)
        document.write({"py_payment_amount": 200})
        document.line_ids.write({
            "py_tax_affectation": "1",
            "py_tax_rate": 10,
            "py_tax_base": 90.91,
            "py_tax_amount": 9.09,
        })
        self._process(document)

        root = self._xml_root_from_attachment(self._xml_attachment(document))

        self.assertEqual(len(root.findall(self._xml_path("DE/gDtipDE/gCamItem"))), 2)

    def test_unsigned_xml_missing_blocking_field_raises(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)
        payload = PyPayloadBuilder(self.env).build(document)
        invalid_payload = deepcopy(payload)
        invalid_payload["receiver"]["nature_code"] = None

        with self.assertRaises(ValidationError):
            PyUnsignedXmlBuilder(self.env).build_from_payload(invalid_payload)

    def test_unsigned_xml_missing_item_code_blocks_schema_readiness(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)
        payload = PyPayloadBuilder(self.env).build(document)
        invalid_payload = deepcopy(payload)
        invalid_payload["items"][0]["code"] = None

        with self.assertRaisesRegex(ValidationError, "item 1 internal code"):
            PyUnsignedXmlBuilder(self.env).build_from_payload(invalid_payload)

    def test_unsigned_xml_unknown_required_code_mapping_blocks_schema_readiness(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)
        payload = PyPayloadBuilder(self.env).build(document)
        invalid_payload = deepcopy(payload)
        invalid_payload["operation"]["transaction_type_code"] = "99"
        invalid_payload["operation"]["transaction_type_description"] = None

        with self.assertRaisesRegex(
            ValidationError,
            "official transaction type description mapping",
        ):
            PyUnsignedXmlBuilder(self.env).build_from_payload(invalid_payload)

    def test_unsigned_xml_missing_issuer_geography_blocks_schema_readiness(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        payload = self._payload_for_xml(document)
        payload["issuer"]["city_name"] = None

        with self.assertRaisesRegex(ValidationError, "issuer establishment city name"):
            PyUnsignedXmlBuilder(self.env).build_from_payload(payload)

    def test_unsigned_xml_missing_economic_activities_blocks_schema_readiness(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        payload = self._payload_for_xml(document)
        payload["issuer"]["economic_activities"] = []

        with self.assertRaisesRegex(ValidationError, "issuer economic activities"):
            PyUnsignedXmlBuilder(self.env).build_from_payload(payload)

        payload = self._payload_for_xml(document)
        payload["issuer"]["economic_activities"][0]["description"] = None
        with self.assertRaisesRegex(
            ValidationError,
            "issuer economic activity 1 description",
        ):
            PyUnsignedXmlBuilder(self.env).build_from_payload(payload)

    def test_unsigned_xml_missing_taxpayer_identity_blocks_schema_readiness(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        payload = self._payload_for_xml(document)
        payload["receiver"]["taxpayer_type"] = None

        with self.assertRaisesRegex(ValidationError, "receiver taxpayer type"):
            PyUnsignedXmlBuilder(self.env).build_from_payload(payload)

        payload = self._payload_for_xml(document)
        payload["receiver"]["ruc_dv"] = None
        with self.assertRaisesRegex(ValidationError, "receiver RUC DV"):
            PyUnsignedXmlBuilder(self.env).build_from_payload(payload)

    def test_unsigned_xml_missing_non_taxpayer_identity_blocks_schema_readiness(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        document.write({
            "customer_tax_id": False,
            "py_receiver_nature": "2",
            "py_receiver_taxpayer_type": False,
            "py_receiver_id_type": "1",
            "py_receiver_id_type_description": "Cedula paraguaya",
            "py_receiver_id_number": "1234567",
        })
        payload = self._payload_for_xml(document)
        payload["receiver"]["id_number"] = None

        with self.assertRaisesRegex(ValidationError, "receiver ID number"):
            PyUnsignedXmlBuilder(self.env).build_from_payload(payload)

    def test_unsigned_xml_innominado_does_not_require_optional_geography(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        payload = self._payload_for_xml(document)
        payload["receiver"].update({
            "nature_code": "2",
            "taxpayer_type": None,
            "ruc_or_document": None,
            "ruc_dv": None,
            "id_type": "5",
            "id_type_description": "Innominado",
            "id_number": "0",
            "house_number": None,
            "department_code": None,
            "department_name": None,
            "district_code": None,
            "district_name": None,
            "city_code": None,
            "city_name": None,
        })

        xml_bytes = PyUnsignedXmlBuilder(self.env).build_from_payload(payload)
        root = ET.fromstring(xml_bytes)

        self.assertIsNone(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/cDepRec"))
        self.assertIsNone(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/dDirRec"))
        self.assertEqual(
            self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/dNumIDRec"),
            "0",
        )

    def test_payload_innominado_does_not_restore_partner_contact_address(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        document.write({
            "customer_tax_id": "0",
            "py_receiver_nature": "2",
            "py_receiver_taxpayer_type": False,
            "py_receiver_id_type": "5",
            "py_receiver_id_type_description": "Innominado",
            "py_receiver_id_number": "0",
            "py_receiver_address": False,
            "py_receiver_house_number": False,
            "py_receiver_department_code": False,
            "py_receiver_department_name": False,
            "py_receiver_district_code": False,
            "py_receiver_district_name": False,
            "py_receiver_city_code": False,
            "py_receiver_city_name": False,
        })

        payload = self._payload_for_xml(document)
        xml_bytes = PyUnsignedXmlBuilder(self.env).build_from_payload(payload)
        root = ET.fromstring(xml_bytes)

        self.assertFalse(payload["receiver"]["address"])
        self.assertIsNone(self._xml_findtext(root, "DE/gDatGralOpe/gDatRec/dDirRec"))

    def test_unsigned_xml_receiver_readiness_blocks_unknown_nature_and_type(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        payload = self._payload_for_xml(document)
        payload["receiver"]["nature_code"] = "9"

        with self.assertRaisesRegex(ValidationError, "receiver nature mapping"):
            PyUnsignedXmlBuilder(self.env).build_from_payload(payload)

        payload = self._payload_for_xml(document)
        payload["receiver"]["type_code"] = "9"
        with self.assertRaisesRegex(ValidationError, "receiver operation type mapping"):
            PyUnsignedXmlBuilder(self.env).build_from_payload(payload)

    def test_unsigned_xml_formatter_helpers(self):
        builder = PyUnsignedXmlBuilder(self.env)

        self.assertEqual(builder._format_money(9.09), "9.09000000")
        self.assertEqual(builder._format_decimal(0, places=4), "0.0000")
        self.assertEqual(builder._format_rate(10.0), "10")
        self.assertEqual(builder._format_date("2026-06-04T12:00:00"), "2026-06-04")
        self.assertEqual(builder._format_datetime("2026-06-04 12:00:00"), "2026-06-04T12:00:00")
        self.assertEqual(builder._normalize_int_code("01"), "1")

    def test_unsigned_xml_non_blocking_warnings_are_allowed(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)
        payload = PyPayloadBuilder(self.env).build(document)
        payload["receiver"]["email"] = None
        payload["warnings"] = ["Receiver email is missing."]

        xml_bytes = PyUnsignedXmlBuilder(self.env).build_from_payload(payload)
        root = ET.fromstring(xml_bytes)

        self.assertEqual(self._xml_find(root, "DE").attrib["Id"], document.py_cdc)

    def test_presignature_validation_accepts_generated_unsigned_xml(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)

        result = PyXmlValidationService().validate_unsigned_presignature(
            self._xml_bytes_for_document(document)
        )

        self.assertTrue(result)

    def test_presignature_validation_malformed_xml_fails(self):
        with self.assertRaisesRegex(ValidationError, "Malformed Paraguay unsigned XML"):
            PyXmlValidationService().validate_unsigned_presignature(b"<rDE>")

    def test_presignature_validation_missing_gacteco_fails(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)
        root = self._xml_root_from_attachment(self._xml_attachment(document))
        issuer = self._xml_find(root, "DE/gDatGralOpe/gEmis")
        for activity in issuer.findall(self._xml_path("gActEco")):
            issuer.remove(activity)

        with self.assertRaisesRegex(ValidationError, "issuer economic activities"):
            PyXmlValidationService().validate_unsigned_presignature(
                self._xml_bytes_from_root(root)
            )

    def test_presignature_validation_missing_taxpayer_identity_fails(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)
        root = self._xml_root_from_attachment(self._xml_attachment(document))
        receiver = self._xml_find(root, "DE/gDatGralOpe/gDatRec")
        receiver.remove(receiver.find(self._xml_path("dDVRec")))

        with self.assertRaisesRegex(ValidationError, "receiver RUC DV"):
            PyXmlValidationService().validate_unsigned_presignature(
                self._xml_bytes_from_root(root)
            )

    def test_presignature_validation_non_taxpayer_receiver_passes(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        document.write({
            "customer_tax_id": False,
            "py_receiver_nature": "2",
            "py_receiver_taxpayer_type": False,
            "py_receiver_id_type": "1",
            "py_receiver_id_type_description": "Cedula paraguaya",
            "py_receiver_id_number": "1234567",
        })
        self._process(document)

        result = PyXmlValidationService().validate_unsigned_presignature(
            self._xml_bytes_for_document(document)
        )

        self.assertTrue(result)

    def test_presignature_validation_missing_non_taxpayer_identity_fails(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        document.write({
            "customer_tax_id": False,
            "py_receiver_nature": "2",
            "py_receiver_taxpayer_type": False,
            "py_receiver_id_type": "1",
            "py_receiver_id_type_description": "Cedula paraguaya",
            "py_receiver_id_number": "1234567",
        })
        self._process(document)
        root = self._xml_root_from_attachment(self._xml_attachment(document))
        receiver = self._xml_find(root, "DE/gDatGralOpe/gDatRec")
        receiver.remove(receiver.find(self._xml_path("dNumIDRec")))

        with self.assertRaisesRegex(ValidationError, "receiver ID number"):
            PyXmlValidationService().validate_unsigned_presignature(
                self._xml_bytes_from_root(root)
            )

    def test_presignature_validation_rejects_signature_stage_fields(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)
        root = self._xml_root_from_attachment(self._xml_attachment(document))
        de = self._xml_find(root, "DE")
        ET.SubElement(de, self._xml_path("dFecFirma")).text = "2026-06-15T20:00:00"

        with self.assertRaisesRegex(ValidationError, "signature timestamp"):
            PyXmlValidationService().validate_unsigned_presignature(
                self._xml_bytes_from_root(root)
            )

    def test_presignature_validation_rejects_signature_element(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)
        root = self._xml_root_from_attachment(self._xml_attachment(document))
        ET.SubElement(root, "Signature").text = "signature-placeholder"

        with self.assertRaisesRegex(ValidationError, "digital signature"):
            PyXmlValidationService().validate_unsigned_presignature(
                self._xml_bytes_from_root(root)
            )

    def test_presignature_validation_rejects_qr_fields(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)
        self._process(document)
        root = self._xml_root_from_attachment(self._xml_attachment(document))
        de = self._xml_find(root, "DE")
        qr_group = ET.SubElement(de, self._xml_path("gCamFuFD"))
        ET.SubElement(qr_group, self._xml_path("dCarQR")).text = "https://example.com/qr"

        with self.assertRaisesRegex(ValidationError, "QR data"):
            PyXmlValidationService().validate_unsigned_presignature(
                self._xml_bytes_from_root(root)
            )

    def test_fake_adapter_creates_payload_and_unsigned_xml_attachments(self):
        self._create_config()
        document = self._create_document()
        self._enrich_standard_cash_invoice(document)

        self._process(document)

        payload_attachment = self.env["fiscal.attachment"].search([
            ("document_id", "=", document.id),
            ("attachment_type", "=", "paraguay_payload_json"),
        ])
        xml_attachment = self._xml_attachment(document)
        self.assertEqual(len(payload_attachment), 1)
        self.assertEqual(len(xml_attachment), 1)
        self.assertEqual(xml_attachment.mimetype, "application/xml")
        self.assertTrue(xml_attachment.sha256)
        self.assertTrue(xml_attachment.ir_attachment_id)
        self.assertTrue(xml_attachment.is_sensitive)

    def test_retry_does_not_duplicate_unsigned_xml_attachment(self):
        self._create_config()
        document = self._create_document(name="PY FAKE RETRY")
        self._enrich_standard_cash_invoice(document)

        self._process(document)
        FiscalOrchestrator(self.env).process_document(
            document,
            actor_context={"actor_type": "system"},
        )

        self.assertEqual(len(self._xml_attachment(document)), 1)

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
