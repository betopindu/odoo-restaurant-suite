from odoo import fields, models


class FiscalDocumentLine(models.Model):
    _inherit = "fiscal.document.line"

    py_internal_code = fields.Char(string="Paraguay Internal Code")
    py_unit_measure_code = fields.Char(
        string="Paraguay Unit Measure Code",
        default="77",
    )
    py_unit_measure_description = fields.Char(
        string="Paraguay Unit Measure",
        default="UNI",
    )
    py_tax_affectation = fields.Selection(
        [
            ("1", "Gravado IVA"),
            ("3", "Exento"),
            ("4", "Gravado parcial"),
        ],
        string="Paraguay Tax Affectation",
    )
    py_tax_rate = fields.Float(string="Paraguay Tax Rate")
    py_tax_proportion = fields.Float(
        string="Paraguay Tax Proportion",
        default=100.0,
    )
    py_tax_base = fields.Float(string="Paraguay Tax Base")
    py_tax_amount = fields.Float(string="Paraguay Tax Amount")
    py_exempt_base = fields.Float(string="Paraguay Exempt Base")
    py_discount_amount = fields.Float(
        string="Paraguay Discount Amount",
        default=0.0,
    )
