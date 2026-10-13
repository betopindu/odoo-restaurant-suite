from odoo import api, fields, models
from odoo.exceptions import AccessError


class PySifenCancellationWizard(models.TransientModel):
    _name = "py.sifen.cancellation.wizard"
    _description = "SIFEN Cancellation Confirmation"

    document_id = fields.Many2one(
        "fiscal.document", required=True, readonly=True,
    )
    document_reference = fields.Char(compute="_compute_context", readonly=True)
    environment_label = fields.Char(compute="_compute_context", readonly=True)
    cdc = fields.Char(compute="_compute_context", readonly=True)
    reason = fields.Text(required=True)
    warning = fields.Text(
        default=(
            "Confirmation performs exactly one SIFEN cancellation event. "
            "It does not delete the document or its accepted evidence."
        ),
        readonly=True,
    )

    @api.depends(
        "document_id", "document_id.source_reference", "document_id.name",
        "document_id.environment", "document_id.country_identifier",
        "document_id.py_cdc",
    )
    def _compute_context(self):
        for wizard in self:
            document = wizard.document_id
            wizard.document_reference = document.source_reference or document.display_name
            wizard.environment_label = (document.environment or "").upper()
            wizard.cdc = document.country_identifier or document.py_cdc

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group("einvoice_py.group_py_fiscal_operator"):
            raise AccessError("Only Paraguay Fiscal Operators may cancel a DTE in SIFEN.")
        result = self._cancellation_service().cancel(
            document=self.document_id,
            reason=self.reason,
        )
        code = result.get("authority_code") or "no authority code"
        message = result.get("authority_message") or "No authority message."
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "SIFEN cancellation completed",
                "message": (
                    f"Transmission {result.get('transmission_id') or '-'}: "
                    f"{code}. {message}"
                ),
                "type": "warning" if result.get("ambiguous") else "info",
                "sticky": True,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def _cancellation_service(self):
        from odoo.addons.einvoice_py.services.py_sifen_event_service import (
            PySifenCancellationService,
        )

        return PySifenCancellationService(self.env)
