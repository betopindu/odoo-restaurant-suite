from odoo import fields, models


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    py_sifen_payment_type_code = fields.Selection(
        [
            ("1", "Cash"),
            ("2", "Cheque"),
            ("3", "Credit card"),
            ("4", "Debit card"),
            ("5", "Bank transfer"),
            ("7", "Electronic wallet"),
            ("16", "Bank payment"),
            ("17", "Mobile payment"),
            ("21", "Electronic payment / QR"),
            ("99", "Other"),
        ],
        string="SIFEN Payment Type",
        help="Official SIFEN payment type used when this method settles a Paraguay fiscal sale.",
    )
