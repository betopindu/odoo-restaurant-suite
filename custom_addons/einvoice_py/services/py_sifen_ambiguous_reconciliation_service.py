import json

from odoo import fields
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_consulta_de_service import (
    PySifenConsultaDeService,
)


class PySifenAmbiguousSubmissionReconciliationService:
    """Resolve an ambiguous TEST submission through SIFEN Consulta DE."""

    def __init__(self, env, *, consulta_de_service=None):
        self.env = env
        self.consulta_de_service = (
            consulta_de_service
            if consulta_de_service is not None
            else PySifenConsultaDeService(env)
        )

    def reconcile(self, *, document=None, cdc=None):
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
        if not ambiguous:
            raise ValidationError(
                "SIFEN Consulta DE reconciliation requires an ambiguous submission."
            )

        query_result = self.consulta_de_service.query(
            document=document,
            cdc=cdc,
        )
        if query_result.get("approved"):
            return self._reconcile_approved(
                document=document,
                transmissions=ambiguous,
                result=query_result,
            )
        if query_result.get("not_approved"):
            return self._reconcile_not_approved(
                document=document,
                transmissions=ambiguous,
                result=query_result,
            )
        return {
            "resolution_status": "unresolved",
            "document_id": document.id,
            "cdc": cdc,
            "query_transmission_id": query_result.get("transmission_id"),
            "authority_code": query_result.get("authority_code") or "",
        }

    def _reconcile_approved(self, *, document, transmissions, result):
        now = fields.Datetime.now()
        receipt_ref = result.get("authority_receipt_ref") or ""
        for transmission in transmissions:
            metadata = self._metadata(transmission)
            metadata.update({
                "ambiguous": False,
                "resolution_status": "accepted_by_cdc_query",
                "query_transmission_id": result["transmission_id"],
                "reconciled_at": fields.Datetime.to_string(now),
            })
            values = {
                "state": "accepted",
                "authority_status_code": result["authority_code"],
                "authority_message": result.get("authority_message") or "",
                "error_code": "",
                "error_message": "",
                "error_type": "",
                "retry_state": "none",
                "next_retry_at": False,
                "finished_at": now,
                "metadata_json": json.dumps(metadata, sort_keys=True),
            }
            transmission.write(values)
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

    def _reconcile_not_approved(self, *, document, transmissions, result):
        now = fields.Datetime.now()
        for transmission in transmissions:
            metadata = self._metadata(transmission)
            metadata.update({
                "ambiguous": False,
                "resolution_status": "not_found_or_not_approved",
                "query_transmission_id": result["transmission_id"],
                "reconciled_at": fields.Datetime.to_string(now),
            })
            transmission.write({
                "state": "failed_final",
                "authority_status_code": result["authority_code"],
                "authority_message": result.get("authority_message") or "",
                "error_code": "remote_not_approved",
                "error_message": (
                    "SIFEN Consulta DE did not find an approved DTE; "
                    "explicit operator action is required."
                ),
                "error_type": "sifen_consulta_de",
                "retry_state": "not_retryable",
                "next_retry_at": False,
                "finished_at": now,
                "metadata_json": json.dumps(metadata, sort_keys=True),
            })
        document.with_context(
            einvoice_skip_fiscal_document_lock=True
        ).write({
            "state": "manual_review",
            "authority_status": result["authority_code"],
        })
        return {
            "resolution_status": "operator_action_required",
            "document_id": document.id,
            "cdc": document.country_identifier or document.py_cdc,
            "query_transmission_id": result["transmission_id"],
            "authority_code": result["authority_code"],
        }

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

    def _already_resolved(self, *, document, cdc):
        if document.state == "accepted":
            accepted = self.env["fiscal.transmission"].sudo().search([
                ("transmission_type", "=", "submit"),
                ("country_code", "=", "PY"),
                ("environment", "=", "test"),
                ("document_id", "=", document.id),
                ("country_identifier", "=", cdc),
                ("state", "=", "accepted"),
            ], limit=1)
            if accepted:
                return {
                    "resolution_status": "accepted",
                    "document_id": document.id,
                    "cdc": cdc,
                    "query_transmission_id": self._query_transmission_id(
                        accepted
                    ),
                    "authority_code": document.authority_status or "",
                }
        resolved = self.env["fiscal.transmission"].sudo().search([
            ("transmission_type", "=", "submit"),
            ("country_code", "=", "PY"),
            ("environment", "=", "test"),
            ("document_id", "=", document.id),
            ("country_identifier", "=", cdc),
            ("error_code", "=", "remote_not_approved"),
        ], limit=1)
        if resolved:
            return {
                "resolution_status": "operator_action_required",
                "document_id": document.id,
                "cdc": cdc,
                "query_transmission_id": self._query_transmission_id(resolved),
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
