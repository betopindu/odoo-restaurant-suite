from odoo import fields, models


class FiscalDocument(models.Model):
    _inherit = "fiscal.document"

    py_establishment_id = fields.Many2one(
        "fiscal.py.establishment",
        string="Paraguay Establishment",
        copy=False,
    )
    py_point_of_issue_id = fields.Many2one(
        "fiscal.py.point.of.issue",
        string="Paraguay Point of Issue",
        copy=False,
    )
    py_timbrado_id = fields.Many2one(
        "fiscal.py.timbrado",
        string="Paraguay Timbrado",
        copy=False,
    )
    py_csc_id = fields.Many2one(
        "fiscal.py.csc",
        string="Paraguay CSC",
        copy=False,
    )
    py_issuer_id = fields.Many2one(
        "fiscal.py.issuer",
        string="Paraguay Issuer",
        copy=False,
    )
    py_issuer_ruc = fields.Char(
        string="Paraguay Issuer RUC",
        copy=False,
    )
    py_issuer_ruc_dv = fields.Char(
        string="Paraguay Issuer RUC DV",
        copy=False,
    )
    py_issuer_taxpayer_type = fields.Selection(
        [
            ("1", "Physical Person"),
            ("2", "Legal Entity"),
        ],
        string="Paraguay Issuer Taxpayer Type",
        copy=False,
    )
    py_document_number = fields.Char(
        string="Paraguay Document Number",
        copy=False,
        index=True,
    )
    py_full_number = fields.Char(
        string="Paraguay Full Number",
        copy=False,
        index=True,
    )
    py_emission_type = fields.Selection(
        [
            ("1", "Normal"),
            ("2", "Contingency"),
        ],
        string="Paraguay Emission Type",
        default="1",
        copy=False,
    )
    py_cod_seg = fields.Char(
        string="Paraguay Security Code",
        copy=False,
    )
    py_cdc_base = fields.Char(
        string="Paraguay CDC Base",
        copy=False,
        index=True,
    )
    py_cdc_dv = fields.Char(
        string="Paraguay CDC DV",
        copy=False,
    )
    py_cdc = fields.Char(
        string="Paraguay CDC",
        copy=False,
        index=True,
    )
    py_receiver_nature = fields.Selection(
        [
            ("1", "Taxpayer"),
            ("2", "Non-taxpayer"),
        ],
        string="Paraguay Receiver Nature",
        copy=False,
        help="Receiver fiscal nature for the Paraguay payload: taxpayer or non-taxpayer.",
    )
    py_receiver_operation_type = fields.Selection(
        [
            ("1", "B2B"),
            ("2", "B2C"),
            ("3", "Foreign"),
        ],
        string="Paraguay Receiver Operation Type",
        copy=False,
        help="Operation type for the receiver: B2B, B2C, or foreign.",
    )
    py_receiver_country_code = fields.Char(
        string="Paraguay Receiver Country",
        default="PRY",
        copy=False,
        help="ISO-style receiver country code used in the Paraguay payload. Use PRY for Paraguay.",
    )
    py_receiver_address = fields.Text(
        string="Paraguay Receiver Address",
        copy=False,
        help="Receiver address included in the normalized Paraguay payload.",
    )
    py_receiver_phone = fields.Char(
        string="Paraguay Receiver Phone",
        copy=False,
        help="Receiver phone included in the normalized Paraguay payload when available.",
    )
    py_transaction_type_code = fields.Selection(
        [
            ("1", "Sale of goods"),
            ("2", "Service provision"),
        ],
        string="Paraguay Transaction Type",
        default="2",
        copy=False,
        help="Transaction type used in the Paraguay payload. Default is service provision.",
    )
    py_tax_type_code = fields.Selection(
        [
            ("1", "IVA"),
            ("4", "None"),
        ],
        string="Paraguay Tax Type",
        default="1",
        copy=False,
        help="Tax type used in the Paraguay payload. Use IVA for normal taxed invoices.",
    )
    py_currency = fields.Char(
        string="Paraguay Currency",
        default="PYG",
        copy=False,
        help="Currency code used in the Paraguay payload. Default is PYG.",
    )
    py_exchange_rate = fields.Float(
        string="Paraguay Exchange Rate",
        copy=False,
        help="Exchange rate required when the Paraguay payload currency is not PYG.",
    )
    py_sale_condition_code = fields.Selection(
        [
            ("1", "Cash"),
            ("2", "Credit"),
        ],
        string="Paraguay Sale Condition",
        default="1",
        copy=False,
        help="Sale condition for the Paraguay payload: cash or credit.",
    )
    py_payment_type_code = fields.Selection(
        [
            ("1", "Cash"),
            ("3", "Credit card"),
            ("5", "Bank transfer"),
            ("17", "Mobile payment"),
        ],
        string="Paraguay Payment Type",
        default="1",
        copy=False,
        help="Payment method for the Paraguay payload, such as cash or bank transfer.",
    )
    py_payment_amount = fields.Monetary(
        string="Paraguay Payment Amount",
        currency_field="currency_id",
        copy=False,
        help="Payment amount to include in the Paraguay payload. Defaults to document total if empty.",
    )
    py_payment_currency = fields.Char(
        string="Paraguay Payment Currency",
        default="PYG",
        copy=False,
        help="Payment currency code used in the Paraguay payload. Default is PYG.",
    )
