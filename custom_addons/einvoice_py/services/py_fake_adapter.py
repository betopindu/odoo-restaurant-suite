from odoo import fields

from odoo.addons.einvoice_module.services.adapter_registry import (
    FakeAdapter,
    FiscalAdapterRegistry,
    FiscalAdapterResult,
)
from odoo.addons.einvoice_module.services.validation import FiscalValidationResult
from odoo.addons.einvoice_py.services.cdc_service import PyCdcService
from odoo.addons.einvoice_py.services.numbering_service import PyNumberingService


class PyFakeAdapter(FakeAdapter):
    code = "py_fake"

    def validate(self, document):
        errors = []
        if (document.country_code or "").upper() != "PY":
            errors.append("Paraguay fake adapter requires country_code PY.")

        config = self._select_config(document)
        if not config["point_of_issue"]:
            errors.append("Active Paraguay point of issue is required.")
        issuer = config["establishment"].issuer_id
        if not issuer:
            errors.append("Active Paraguay issuer is required.")
        elif (issuer.environment or "") != document.environment:
            errors.append("Paraguay issuer environment must match the document environment.")
        elif not issuer.ruc or not issuer.ruc_dv or not issuer.taxpayer_type:
            errors.append("Paraguay issuer RUC, DV, and taxpayer type are required.")
        if not config["timbrado"]:
            errors.append("Active Paraguay timbrado is required.")
        if not config["csc"]:
            errors.append("Active Paraguay CSC is required.")
        if not document.py_document_number and not self._has_matching_sequence(document, config):
            errors.append("Active Paraguay sequence is required.")
        errors.extend(self._cdc_validation_errors(document, config))

        return FiscalValidationResult(errors)

    def submit(self, document):
        config = self._select_config(document)
        self._persist_config(document, config)
        PyNumberingService(self.env).assign_number(document)
        PyCdcService(self.env).generate(document)
        outcome = self._outcome_from_document(document)
        return FiscalAdapterResult(
            outcome=outcome,
            authority_status_code=outcome,
            authority_message=self._message_from_outcome(outcome),
            country_identifier=document.py_cdc if outcome == "accepted" else "",
            authority_receipt_ref=f"PY-FAKE-{document.uuid}",
            retryable=outcome == "failed_retryable",
            retry_after_seconds=300 if outcome == "failed_retryable" else 0,
            metadata_json={
                "mode": "fake",
                "adapter_code": self.code,
                "source": "einvoice_py",
                "matched_outcome": outcome,
                "py_establishment_code": config["establishment"].code,
                "py_issuer_ruc": config["establishment"].issuer_id.ruc,
                "py_point_of_issue_code": config["point_of_issue"].code,
                "py_timbrado_number": config["timbrado"].number,
                "py_id_csc": config["csc"].id_csc,
                "py_full_number": document.py_full_number,
                "py_cdc": document.py_cdc,
            },
        )

    def _select_config(self, document):
        point_of_issue = document.py_point_of_issue_id or self._select_point_of_issue(document)
        establishment = (
            document.py_establishment_id
            or point_of_issue.establishment_id
            or self.env["fiscal.py.establishment"]
        )
        return {
            "point_of_issue": point_of_issue,
            "establishment": establishment,
            "timbrado": document.py_timbrado_id or self._select_timbrado(document, point_of_issue),
            "csc": document.py_csc_id or self._select_csc(document),
        }

    def _base_domain(self, document):
        return [
            ("tenant_id", "=", document.tenant_id.id),
            ("company_id", "=", document.company_id.id),
            ("active", "=", True),
        ]

    def _select_point_of_issue(self, document):
        return self.env["fiscal.py.point.of.issue"].search(
            self._base_domain(document),
            order="id asc",
            limit=1,
        )

    def _select_timbrado(self, document, point_of_issue):
        today = fields.Date.today()
        domain = self._base_domain(document) + [
            ("environment", "=", document.environment),
            ("document_type", "=", document.document_type),
            "|",
            ("valid_from", "=", False),
            ("valid_from", "<=", today),
            "|",
            ("valid_to", "=", False),
            ("valid_to", ">=", today),
        ]
        candidates = self.env["fiscal.py.timbrado"].search(domain, order="id asc")
        if point_of_issue:
            candidates = candidates.filtered(
                lambda timbrado: (
                    not timbrado.allowed_point_of_issue_ids
                    or point_of_issue in timbrado.allowed_point_of_issue_ids
                )
            )
        return candidates[:1]

    def _select_csc(self, document):
        today = fields.Date.today()
        return self.env["fiscal.py.csc"].search(
            self._base_domain(document)
            + [
                ("environment", "=", document.environment),
                "|",
                ("valid_from", "=", False),
                ("valid_from", "<=", today),
                "|",
                ("valid_to", "=", False),
                ("valid_to", ">=", today),
            ],
            order="id asc",
            limit=1,
        )

    def _persist_config(self, document, config):
        issuer = config["establishment"].issuer_id
        document.with_context(einvoice_skip_fiscal_document_lock=True).write({
            "py_establishment_id": config["establishment"].id,
            "py_point_of_issue_id": config["point_of_issue"].id,
            "py_timbrado_id": config["timbrado"].id,
            "py_csc_id": config["csc"].id,
            "py_issuer_id": issuer.id,
            "py_issuer_ruc": issuer.ruc,
            "py_issuer_ruc_dv": issuer.ruc_dv,
            "py_issuer_taxpayer_type": issuer.taxpayer_type,
        })

    def _has_matching_sequence(self, document, config):
        if not config["establishment"] or not config["point_of_issue"] or not config["timbrado"]:
            return False
        return bool(
            PyNumberingService(self.env).find_sequence(
                document,
                establishment=config["establishment"],
                point_of_issue=config["point_of_issue"],
                timbrado=config["timbrado"],
            )
        )

    def _cdc_validation_errors(self, document, config):
        if document.py_cdc:
            return []
        issuer = config["establishment"].issuer_id
        require_document_number = bool(document.py_document_number)
        return PyCdcService(self.env).validation_errors(
            document,
            establishment=config["establishment"],
            point_of_issue=config["point_of_issue"],
            issuer=issuer,
            require_document_number=require_document_number,
        )

    def _message_from_outcome(self, outcome):
        return {
            "accepted": "Paraguay fake accepted response",
            "rejected": "Paraguay fake rejected response",
            "failed_retryable": "Paraguay fake retryable failure response",
            "failed_final": "Paraguay fake final failure response",
            "manual_review": "Paraguay fake manual review response",
        }.get(outcome, "Paraguay fake unknown response")


FiscalAdapterRegistry.ADAPTERS[PyFakeAdapter.code] = PyFakeAdapter
