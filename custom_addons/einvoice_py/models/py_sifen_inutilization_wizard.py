from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class PySifenInutilizationWizard(models.TransientModel):
    _name = "py.sifen.inutilization.wizard"
    _description = "SIFEN Number Inutilization Confirmation"

    adapter_config_id = fields.Many2one(
        "fiscal.adapter.config", required=True,
        domain="[('country_code', '=', 'PY'), ('adapter_code', '=', 'py_sifen')]",
    )
    environment_label = fields.Char(
        compute="_compute_environment_label", readonly=True,
    )
    timbrado_id = fields.Many2one("fiscal.py.timbrado", required=True)
    establishment_id = fields.Many2one("fiscal.py.establishment", required=True)
    point_of_issue_id = fields.Many2one("fiscal.py.point.of.issue", required=True)
    document_type = fields.Selection(
        [
            ("invoice", "Invoice"),
            ("credit_note", "Credit Note"),
            ("debit_note", "Debit Note"),
        ],
        required=True,
    )
    number_from = fields.Integer(required=True)
    number_to = fields.Integer(required=True)
    occurred_on = fields.Date(
        required=True, default=fields.Date.context_today,
    )
    reason = fields.Char(required=True)
    warning = fields.Text(
        default=(
            "Confirmation performs exactly one SIFEN number-inutilization event. "
            "The range must never have been issued and cannot be reused after acceptance."
        ),
        readonly=True,
    )

    @api.onchange("timbrado_id")
    def _onchange_timbrado_id(self):
        if self.timbrado_id:
            self.document_type = self.timbrado_id.document_type

    @api.depends("adapter_config_id", "adapter_config_id.environment")
    def _compute_environment_label(self):
        for wizard in self:
            wizard.environment_label = (
                wizard.adapter_config_id.environment or ""
            ).upper()

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group("einvoice_py.group_py_fiscal_operator"):
            raise AccessError(
                "Only Paraguay Fiscal Operators may inutilize numbers in SIFEN."
            )
        if self.adapter_config_id.tenant_id not in self.env.user.allowed_fiscal_tenant_ids:
            raise AccessError("The selected fiscal tenant is not available to this operator.")
        if self.adapter_config_id.company_id not in self.env.companies:
            raise AccessError("The selected fiscal company is not available to this operator.")
        result = self._inutilization_service().inutilize(
            adapter=self.adapter_config_id,
            timbrado=self.timbrado_id,
            establishment=self.establishment_id,
            point_of_issue=self.point_of_issue_id,
            document_type=self.document_type,
            number_from=self.number_from,
            number_to=self.number_to,
            reason=self.reason,
            occurred_on=self.occurred_on,
        )
        code = result.get("authority_code") or "no authority code"
        message = result.get("authority_message") or "No authority message."
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "SIFEN inutilization completed",
                "message": (
                    f"Evidence {result.get('inutilization_id') or '-'}: "
                    f"{code}. {message}"
                ),
                "type": "warning" if result.get("ambiguous") else "info",
                "sticky": True,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def _inutilization_service(self):
        from odoo.addons.einvoice_py.services.py_sifen_event_service import (
            PySifenInutilizationService,
        )

        return PySifenInutilizationService(self.env)
