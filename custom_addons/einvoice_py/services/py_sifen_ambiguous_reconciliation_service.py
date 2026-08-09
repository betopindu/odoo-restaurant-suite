import json

from odoo import fields
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_consulta_de_service import (
    PySifenConsultaDeService,
)


class PySifenReconciliationService:
    """Resolve an ambiguous TEST submission through SIFEN Consulta DE."""

    def __init__(self, env, *, consulta_de_service=None):
        self.env = env
        self.consulta_de_service = (
            consulta_de_service
            if consulta_de_service is not None
            else PySifenConsultaDeService(env)
        )

    def reconcile(self, *, document=None, cdc=None, operator_requested=False):
        document = self._document(document=document, cdc=cdc)
        cdc = (
            cdc
            or document.country_identifier
            or document.py_cdc
            or ""
        ).strip()
        document.ensure_one()
        self._lock_document(document)
        resolved = self._already_resolved(document=document, cdc=cdc)
        if resolved:
            return resolved
        ambiguous = self._ambiguous_transmissions(document)
        submissions = self._submission_transmissions(document)
        if not ambiguous and not operator_requested:
            raise ValidationError(
                "SIFEN Consulta DE reconciliation requires an ambiguous submission."
            )
        if operator_requested and not submissions:
            raise ValidationError(
                "SIFEN diagnostic Consulta DE requires a previous submission."
            )

        query_result = self.consulta_de_service.query(
            document=document,
            cdc=cdc,
        )
        self._link_query_evidence(
            query_transmission_id=query_result.get("transmission_id"),
            submissions=ambiguous or submissions,
            operator_requested=operator_requested,
        )
        if query_result.get("approved"):
            return self._reconcile_approved(
                document=document,
                result=query_result,
            )
        if query_result.get("not_approved"):
            return self._reconcile_not_approved(
                document=document,
                result=query_result,
            )
        return {
            "resolution_status": "unresolved",
            "document_id": document.id,
            "cdc": cdc,
            "query_transmission_id": query_result.get("transmission_id"),
            "authority_code": query_result.get("authority_code") or "",
        }

    def _reconcile_approved(self, *, document, result):
        now = fields.Datetime.now()
        receipt_ref = result.get("authority_receipt_ref") or ""
        document_values = {
            "state": "accepted",
            "authority_status": result["authority_code"],
            "accepted_at": now,
        }
        if receipt_ref:
            document_values["authority_receipt_ref"] = receipt_ref
        document.with_context(
            einvoice_skip_fiscal_document_lock=True
        ).write(document_values)
        return {
            "resolution_status": "accepted",
            "document_id": document.id,
            "cdc": document.country_identifier or document.py_cdc,
            "query_transmission_id": result["transmission_id"],
            "authority_code": result["authority_code"],
        }

    def _reconcile_not_approved(self, *, document, result):
        document.with_context(
            einvoice_skip_fiscal_document_lock=True
        ).write({
            "state": "manual_review",
            "authority_status": result["authority_code"],
        })
        return {
            "resolution_status": "reconciliation_not_found",
            "document_id": document.id,
            "cdc": document.country_identifier or document.py_cdc,
            "query_transmission_id": result["transmission_id"],
            "authority_code": result["authority_code"],
        }

    def _link_query_evidence(self, *, query_transmission_id, submissions, operator_requested):
        if not query_transmission_id:
            return
        query = self.env["fiscal.transmission"].sudo().browse(query_transmission_id)
        metadata = self._metadata(query)
        metadata.update({
            "original_submission_ids": submissions.ids,
            "operator_requested": bool(operator_requested),
        })
        query.write({"metadata_json": json.dumps(metadata, sort_keys=True)})

    def _document(self, *, document, cdc):
        if document:
            document.ensure_one()
            if cdc and cdc not in {
                document.country_identifier,
                document.py_cdc,
            }:
                raise ValidationError(
                    "SIFEN reconciliation CDC must match the document CDC."
                )
            return document
        normalized_cdc = (cdc or "").strip()
        if not normalized_cdc:
            raise ValidationError(
                "SIFEN reconciliation requires a document or CDC."
            )
        documents = self.env["fiscal.document"].search([
            ("country_code", "=", "PY"),
            ("environment", "=", "test"),
            "|",
            ("country_identifier", "=", normalized_cdc),
            ("py_cdc", "=", normalized_cdc),
        ])
        if len(documents) != 1:
            raise ValidationError(
                "SIFEN reconciliation CDC must identify exactly one TEST document."
            )
        return documents

    def _lock_document(self, document):
        self.env.cr.execute(
            """
            SELECT id
              FROM fiscal_document
             WHERE id = %s
             FOR UPDATE
            """,
            [document.id],
        )
        if not self.env.cr.fetchone():
            raise ValidationError(
                "SIFEN reconciliation document no longer exists."
            )

    def _ambiguous_transmissions(self, document):
        return self.env["fiscal.transmission"].sudo().search([
            ("transmission_type", "=", "submit"),
            ("country_code", "=", "PY"),
            ("environment", "=", "test"),
            ("tenant_id", "=", document.tenant_id.id),
            ("company_id", "=", document.company_id.id),
            ("country_identifier", "=", (
                document.country_identifier or document.py_cdc
            )),
            "|",
            ("state", "=", "sent"),
            ("error_code", "=", "ambiguous_submission"),
        ])

    def _submission_transmissions(self, document):
        return self.env["fiscal.transmission"].sudo().search([
            ("transmission_type", "=", "submit"),
            ("country_code", "=", "PY"),
            ("environment", "=", "test"),
            ("tenant_id", "=", document.tenant_id.id),
            ("company_id", "=", document.company_id.id),
            ("country_identifier", "=", (
                document.country_identifier or document.py_cdc
            )),
        ])

    def _already_resolved(self, *, document, cdc):
        if document.state == "accepted":
            query = self.env["fiscal.transmission"].sudo().search([
                ("transmission_type", "=", "status_query"),
                ("document_id", "=", document.id),
                ("country_identifier", "=", cdc),
                ("state", "=", "accepted"),
            ], order="id desc", limit=1)
            return {
                "resolution_status": "accepted",
                "document_id": document.id,
                "cdc": cdc,
                "query_transmission_id": query.id or None,
                "authority_code": document.authority_status or "",
            }
        resolved = self.env["fiscal.transmission"].sudo().search([
            ("transmission_type", "=", "status_query"),
            ("country_code", "=", "PY"),
            ("environment", "=", "test"),
            ("document_id", "=", document.id),
            ("country_identifier", "=", cdc),
            ("error_code", "=", "reconciliation_not_found"),
        ], order="id desc", limit=1)
        if resolved:
            return {
                "resolution_status": "reconciliation_not_found",
                "document_id": document.id,
                "cdc": cdc,
                "query_transmission_id": resolved.id,
                "authority_code": resolved.authority_status_code or "",
            }
        return None

    def _query_transmission_id(self, transmission):
        return self._metadata(transmission).get("query_transmission_id")

    def _metadata(self, transmission):
        try:
            metadata = json.loads(transmission.metadata_json or "{}")
        except (TypeError, ValueError):
            return {}
        return metadata if isinstance(metadata, dict) else {}


# Backward-compatible Stage 8.24A name.
PySifenAmbiguousSubmissionReconciliationService = PySifenReconciliationService
