from odoo import fields, models


class FiscalAdapterConfig(models.Model):
    _name = "fiscal.adapter.config"
    _description = "Fiscal Adapter Configuration"
    _order = "tenant_id, country_code, environment, adapter_code"

    name = fields.Char(required=True)
    tenant_id = fields.Many2one("fiscal.tenant", required=True, index=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    country_code = fields.Char(size=2, required=True, index=True)
    adapter_code = fields.Char(required=True, index=True)
    environment = fields.Selection(
        [("test", "Test"), ("production", "Production")],
        default="test",
        required=True,
    )

    credentials_mode = fields.Selection(
        [
            ("odoo_storage", "Odoo Storage"),
            ("external_secret", "External Secret"),
            ("kms", "KMS"),
            ("manual", "Manual"),
        ],
        default="manual",
        required=True,
    )
    certificate_ref = fields.Char()
    private_key_ref = fields.Char()
    api_client_id = fields.Char()
    token_ref = fields.Char()

    numbering_strategy = fields.Selection(
        [
            ("odoo_sequence", "Odoo Sequence"),
            ("external_authority", "External Authority"),
            ("adapter_managed", "Adapter Managed"),
            ("api_provided", "API Provided"),
        ],
        default="odoo_sequence",
        required=True,
    )
    sequence_prefix = fields.Char()
    sequence_id = fields.Many2one("ir.sequence")
    endpoint_base_url = fields.Char()
    timeout_seconds = fields.Integer(default=30)
    max_retry_count = fields.Integer(default=3)
    metadata_json = fields.Text()
