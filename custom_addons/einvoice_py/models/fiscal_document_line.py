from odoo import fields, models


class FiscalDocumentLine(models.Model):
    _inherit = "fiscal.document.line"

    py_internal_code = fields.Char(
        string="Internal Code",
        help="Internal item/service code to include in the Paraguay payload.",
    )
    py_unit_measure_code = fields.Char(
        string="Unit Measure Code",
        default="77",
        help="SIFEN unit measure code. Use 77 for units (UNI) in the current MVP.",
    )
    py_unit_measure_description = fields.Char(
        string="Unit Measure",
        default="UNI",
        help="Readable unit measure description. Use UNI for unit-based lines.",
    )
    py_tax_affectation = fields.Selection(
        [
            ("1", "Taxed by IVA"),
            ("3", "Exempt"),
            ("4", "Partially taxed"),
        ],
        string="Tax Affectation",
        help=(
            "Use Taxed by IVA for IVA 5% or 10% lines, Exempt for non-taxed lines, "
            "and Partially taxed when a line has both taxable and exempt bases."
        ),
    )
    py_tax_rate = fields.Float(
        string="Fiscal Tax Rate",
        help="IVA rate for the line. Expected values for MVP: 0, 5, or 10.",
    )
    py_tax_proportion = fields.Float(
        string="Tax Proportion",
        default=100.0,
        help="Taxable proportion of the line. Use 100 for fully taxable IVA lines.",
    )
    py_tax_base = fields.Float(
        string="Tax Base",
        help="Taxable base amount used for IVA 5% or IVA 10% bucket calculation.",
    )
    py_tax_amount = fields.Float(
        string="Fiscal Tax Amount",
        help="IVA amount for the line. Used in total VAT 5% or 10% buckets.",
    )
    py_exempt_base = fields.Float(
        string="Exempt Base",
        help="Exempt amount for Exempt or Partially taxed lines.",
    )
    py_discount_amount = fields.Float(
        string="Discount Amount",
        default=0.0,
        help="Line discount amount to include in the normalized Paraguay payload.",
    )
