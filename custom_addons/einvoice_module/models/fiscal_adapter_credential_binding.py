from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FiscalAdapterCredentialBinding(models.Model):
    _name = "fiscal.adapter.credential.binding"
    _description = "Fiscal Adapter Credential Role Binding"
    _order = "adapter_config_id, role"

    adapter_config_id = fields.Many2one(
        "fiscal.adapter.config",
        required=True,
        index=True,
        ondelete="cascade",
    )
    credential_id = fields.Many2one(
        "fiscal.credential",
        required=True,
        index=True,
        ondelete="restrict",
    )
    role = fields.Selection(
        [
            ("xml_signing", "XML Signing"),
            ("mutual_tls", "Mutual TLS"),
        ],
        required=True,
        index=True,
    )
    tenant_id = fields.Many2one(
        "fiscal.tenant",
        related="adapter_config_id.tenant_id",
        store=True,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="adapter_config_id.company_id",
        store=True,
        index=True,
    )

    _sql_constraints = [
        (
            "adapter_role_unique",
            "unique(adapter_config_id, role)",
            "Each adapter configuration can bind only one credential per role.",
        ),
    ]

    @api.constrains("adapter_config_id", "credential_id")
    def _check_credential_scope(self):
        for binding in self:
            adapter = binding.adapter_config_id
            credential = binding.credential_id
            if adapter.tenant_id != credential.tenant_id:
                raise ValidationError(
                    "Credential and adapter configuration must belong to the same tenant."
                )
            if adapter.company_id != credential.company_id:
                raise ValidationError(
                    "Credential and adapter configuration must belong to the same company."
                )
