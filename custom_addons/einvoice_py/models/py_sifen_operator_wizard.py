from odoo import fields, models
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_operator_service import (
    PySifenOperatorService,
)


class PySifenOperatorWizard(models.TransientModel):
    _name = "py.sifen.operator.wizard"
    _description = "SIFEN Operator Confirmation"

    document_id = fields.Many2one("fiscal.document", required=True, readonly=True)
    operation = fields.Selection(
        [("submit", "Submit / Manual Retry"), ("reconcile", "Consulta DE Recovery")],
        required=True,
        readonly=True,
    )
    warning = fields.Text(readonly=True)

    def action_confirm(self):
        self.ensure_one()
        service = PySifenOperatorService(self.env)
        if self.operation == "submit":
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
