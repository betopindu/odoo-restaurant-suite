from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_module.services.orchestrator import FiscalOrchestrator


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
    ):
        if not establishment:
            establishment = self.env["fiscal.py.establishment"].create({
                "name": f"Main Establishment {point_code}",
                "code": "001",
                "tenant_id": self.tenant.id,
                "company_id": self.env.company.id,
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

    def _create_document(self, name="PY FAKE ACCEPT", document_type="invoice"):
        return self.env["fiscal.document"].create({
            "name": name,
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": document_type,
            "country_code": "PY",
            "environment": "test",
            "adapter_code": "py_fake",
            "customer_name": "Paraguay Test Customer",
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
        })

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
        self.assertTrue(document.country_identifier.startswith("PY-FAKE-"))

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
        self.assertEqual(sequence.next_number, 16)

        FiscalOrchestrator(self.env).process_document(
            document,
            actor_context={"actor_type": "system"},
        )

        self.assertEqual(document.py_document_number, first_number)
        self.assertEqual(document.py_full_number, first_full_number)
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
