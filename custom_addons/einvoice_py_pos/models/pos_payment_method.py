from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    PY_SIFEN_CARD_DENOMINATIONS = {
        "1": "Visa",
        "2": "Mastercard",
        "3": "American Express",
        "4": "Maestro",
        "5": "Panal",
        "6": "Cabal",
        "99": "Otro",
    }

    py_sifen_payment_type_code = fields.Selection(
        [
            ("1", "Cash"),
            ("2", "Cheque (not available for fiscal POS)"),
            ("3", "Credit card"),
            ("4", "Debit card"),
            ("5", "Bank transfer"),
            ("7", "Electronic wallet"),
            ("16", "Bank payment (not available for fiscal POS)"),
            ("17", "Mobile payment"),
            ("21", "Electronic payment / QR"),
            ("99", "Other (not available for fiscal POS)"),
        ],
        string="SIFEN Payment Type",
        help="Official SIFEN payment type used when this method settles a Paraguay fiscal sale.",
    )
    py_sifen_card_denomination = fields.Selection(
        [(code, description) for code, description in PY_SIFEN_CARD_DENOMINATIONS.items()],
        string="SIFEN Card Brand",
    )
    py_sifen_card_processing = fields.Selection(
        [("1", "POS terminal"), ("2", "Electronic payment"), ("9", "Other")],
        string="SIFEN Card Processing",
    )
    py_sifen_card_processor_name = fields.Char(string="Card Processor Name")
    py_sifen_card_processor_ruc = fields.Char(string="Card Processor RUC")
    py_sifen_card_processor_dv = fields.Char(string="Card Processor DV", size=1)

    def _py_sifen_card_snapshot(self):
        self.ensure_one()
        if self.py_sifen_payment_type_code not in ("3", "4"):
            return None
        denomination = self.py_sifen_card_denomination
        processing = self.py_sifen_card_processing
        if not denomination or not processing:
            return None
        processor_values = (
            self.py_sifen_card_processor_name,
            self.py_sifen_card_processor_ruc,
            self.py_sifen_card_processor_dv,
        )
        if any(processor_values) and not all(processor_values):
            return None
        if self.py_sifen_card_processor_ruc and (
            not self.py_sifen_card_processor_ruc.isdigit()
            or not 3 <= len(self.py_sifen_card_processor_ruc) <= 8
            or not self.py_sifen_card_processor_dv.isdigit()
            or len(self.py_sifen_card_processor_dv) != 1
            or not 4 <= len(self.py_sifen_card_processor_name) <= 60
        ):
            return None
        return {
            "denomination_code": denomination,
            "denomination_description": self.PY_SIFEN_CARD_DENOMINATIONS[denomination],
            "processing_code": processing,
            "processor_name": self.py_sifen_card_processor_name or None,
            "processor_ruc": self.py_sifen_card_processor_ruc or None,
            "processor_dv": self.py_sifen_card_processor_dv or None,
        }

    @api.constrains(
        "py_sifen_payment_type_code",
        "py_sifen_card_denomination",
        "py_sifen_card_processing",
        "py_sifen_card_processor_name",
        "py_sifen_card_processor_ruc",
        "py_sifen_card_processor_dv",
    )
    def _check_py_sifen_fiscal_pos_usage(self):
        fiscal_configs = self.env["pos.config"].search([
            ("py_fiscal_checkout_enabled", "=", True),
            ("payment_method_ids", "in", self.ids),
        ])
        for method in self:
            if not fiscal_configs.filtered(lambda config: method in config.payment_method_ids):
                continue
            if not method.py_sifen_payment_type_code:
                raise ValidationError(
                    "A payment method used by Paraguay fiscal POS requires a SIFEN payment type."
                )
            if (
                method.py_sifen_payment_type_code
                not in self.env["pos.config"].PY_SIFEN_SUPPORTED_POS_PAYMENT_TYPES
            ):
                raise ValidationError(
                    "This SIFEN payment type is not supported by Paraguay fiscal POS."
                )
            if method.py_sifen_payment_type_code in ("3", "4"):
                if not method._py_sifen_card_snapshot():
                    raise ValidationError(
                        "A Paraguay fiscal card method requires brand, processing method "
                        "and a complete processor identity when provided."
                    )
