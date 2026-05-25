from odoo import fields, models

from odoo.addons.fiscal_api.services.authentication import FiscalApiAuthenticationService


class FiscalApiKey(models.Model):
    _name = "fiscal.api.key"
    _description = "Fiscal API Key"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    tenant_id = fields.Many2one("fiscal.tenant", required=True, index=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    key_prefix = fields.Char(readonly=True, copy=False, index=True)
    key_hash = fields.Char(readonly=True, copy=False)
    default_processing_mode = fields.Selection(
        [
            ("async", "Async"),
            ("sync", "Sync"),
        ],
        default="async",
        required=True,
    )
    last_used_at = fields.Datetime(readonly=True, copy=False)
    expires_at = fields.Datetime(copy=False)
    revoked_at = fields.Datetime(readonly=True, copy=False)
    description = fields.Text()

    def action_generate_api_key(self):
        self.ensure_one()
        authentication = FiscalApiAuthenticationService(self.env)
        raw_key = authentication.generate_raw_key()
        self.write({
            "key_prefix": authentication.key_prefix(raw_key),
            "key_hash": authentication.hash_key(raw_key),
            "revoked_at": False,
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "API Key Generated",
                "message": (
                    "Copy this API key now. It will not be shown again:\n"
                    f"{raw_key}"
                ),
                "type": "warning",
                "sticky": True,
            },
        }
