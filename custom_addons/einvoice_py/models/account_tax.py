from odoo import fields, models


class AccountTax(models.Model):
    _inherit = "account.tax"

    py_sifen_tax_treatment = fields.Selection(
        [("iva_10", "SIFEN IVA 10%"), ("iva_5", "SIFEN IVA 5%"), ("exempt", "SIFEN Exempt")],
        string="Paraguay SIFEN Tax Treatment",
        help="Explicit mapping used for fiscal snapshots; tax names are never interpreted.",
    )
