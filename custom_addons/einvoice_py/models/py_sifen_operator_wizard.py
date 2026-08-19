from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_operator_service import (
    PySifenOperatorService,
)


class PySifenOperatorWizard(models.TransientModel):
    _name = "py.sifen.operator.wizard"
    _description = "SIFEN Operator Confirmation"

    document_id = fields.Many2one(
        "fiscal.document",
        string="Fiscal Document Record",
        required=True,
        readonly=True,
    )
    operation = fields.Selection(
        [
            ("submit", "Submit to SIFEN"),
            ("manual_retry", "Manual Retry to SIFEN"),
            ("reconcile", "Consulta DE Recovery"),
        ],
        required=True,
        readonly=True,
    )
    document_reference = fields.Char(
        string="Document",
        compute="_compute_document_context",
        readonly=True,
    )
    environment_label = fields.Char(
        string="Environment",
        compute="_compute_document_context",
        readonly=True,
    )
    cdc = fields.Char(
        string="CDC",
        compute="_compute_document_context",
        readonly=True,
    )
    warning = fields.Text(readonly=True)

    @api.depends(
        "document_id",
        "document_id.source_reference",
        "document_id.account_move_id.name",
        "document_id.name",
        "document_id.environment",
        "document_id.country_identifier",
        "document_id.py_cdc",
    )
    def _compute_document_context(self):
        for wizard in self:
            document = wizard.document_id
            wizard.document_reference = (
                document.source_reference
                or document.account_move_id.name
                or document.display_name
            )
            wizard.environment_label = (document.environment or "").upper()
            wizard.cdc = document.country_identifier or document.py_cdc

    def action_confirm(self):
        self.ensure_one()
        service = PySifenOperatorService(self.env)
        if self.operation in ("submit", "manual_retry"):
            result = service.submit(document=self.document_id)
            message = self._submission_message(result)
        elif self.operation == "reconcile":
            result = service.reconcile(document=self.document_id)
            message = self._reconciliation_message(result)
        else:
            raise ValidationError("Unsupported SIFEN operator operation.")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "SIFEN operation completed",
                "message": message,
                "type": "warning" if result.get("ambiguous") else "info",
                "sticky": True,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    @staticmethod
    def _submission_message(result):
        status = result.get("submission_status") or "unknown"
        code = result.get("authority_code") or "no authority code"
        message = result.get("authority_message") or "No authority message."
        return f"Transmission {result.get('transmission_id') or '-'}: {status} / {code}. {message}"

    @staticmethod
    def _reconciliation_message(result):
        status = result.get("resolution_status") or "unresolved"
        code = result.get("authority_code") or "no authority code"
        return f"Consulta DE {result.get('query_transmission_id') or '-'}: {status} / {code}."
