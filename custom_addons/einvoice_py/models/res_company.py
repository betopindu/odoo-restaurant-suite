from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    py_auto_email_accepted_fiscal_documents = fields.Boolean(
        string="Automatically email accepted Paraguay fiscal documents",
        default=False,
        help="Queues the authoritative KuDE and XML after acceptance. Disabled by default.",
    )
    py_fiscal_email_from = fields.Char(
        string="Paraguay fiscal email sender",
        help="Sender used for Paraguay fiscal deliveries. Falls back to the company email.",
    )
