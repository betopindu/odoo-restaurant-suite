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

    def _create_config(self):
        establishment = self.env["fiscal.py.establishment"].create({
            "name": "Main Establishment",
            "code": "001",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
        })
        point_of_issue = self.env["fiscal.py.point.of.issue"].create({
            "name": "Main Point",
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
            "name": "Test CSC",
            "id_csc": "1",
            "csc_value": "test-csc-value",
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "environment": "test",
        })
        return establishment, point_of_issue, timbrado, csc

    def _create_document(self, name="PY FAKE ACCEPT"):
        return self.env["fiscal.document"].create({
            "name": name,
            "tenant_id": self.tenant.id,
            "company_id": self.env.company.id,
            "document_type": "invoice",
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
        establishment, point_of_issue, timbrado, csc = self._create_config()
        document = self._create_document()

        self._process(document)

        self.assertEqual(document.py_establishment_id, establishment)
        self.assertEqual(document.py_point_of_issue_id, point_of_issue)
        self.assertEqual(document.py_timbrado_id, timbrado)
        self.assertEqual(document.py_csc_id, csc)
