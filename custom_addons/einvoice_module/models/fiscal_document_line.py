from odoo import fields, models


class FiscalDocumentLine(models.Model):
    _name = "fiscal.document.line"
    _description = "Fiscal Document Line"
    _order = "document_id, sequence, id"

    document_id = fields.Many2one("fiscal.document", required=True, ondelete="cascade", index=True)
    tenant_id = fields.Many2one(related="document_id.tenant_id", store=True, readonly=True)
    company_id = fields.Many2one(related="document_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="document_id.currency_id", store=True, readonly=True)

    sequence = fields.Integer(default=10)
    source_line_id = fields.Integer(index=True)
    source_external_line_id = fields.Char(index=True)

    product_id = fields.Many2one("product.product")
    product_code = fields.Char()
    product_name = fields.Char(required=True)
    description = fields.Text()
    quantity = fields.Float(default=1.0)
    uom_id = fields.Many2one("uom.uom")
    price_unit = fields.Monetary(currency_field="currency_id")
    discount = fields.Float()
    subtotal = fields.Monetary(currency_field="currency_id")
    tax_amount = fields.Monetary(currency_field="currency_id")
    total = fields.Monetary(currency_field="currency_id")
    tax_ids = fields.Many2many("account.tax", string="Taxes")

    tax_category_code = fields.Char()
    tax_rate = fields.Float()
    tax_base_amount = fields.Monetary(currency_field="currency_id")
    fiscal_product_code = fields.Char()
    fiscal_unit_code = fields.Char()
    metadata_json = fields.Text()
