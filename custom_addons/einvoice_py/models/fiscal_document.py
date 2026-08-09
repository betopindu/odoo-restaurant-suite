from odoo import fields, models


class FiscalDocument(models.Model):
    _inherit = "fiscal.document"

    py_establishment_id = fields.Many2one(
        "fiscal.py.establishment",
        string="Establishment",
        copy=False,
    )
    py_point_of_issue_id = fields.Many2one(
        "fiscal.py.point.of.issue",
        string="Point of Issue",
        copy=False,
    )
    py_timbrado_id = fields.Many2one(
        "fiscal.py.timbrado",
        string="Timbrado",
        copy=False,
    )
    py_csc_id = fields.Many2one(
        "fiscal.py.csc",
        string="CSC",
        copy=False,
    )
    py_issuer_id = fields.Many2one(
        "fiscal.py.issuer",
        string="Issuer",
        copy=False,
    )
    py_issuer_ruc = fields.Char(
        string="Issuer RUC",
        copy=False,
    )
    py_issuer_ruc_dv = fields.Char(
        string="Issuer RUC DV",
        copy=False,
    )
    py_issuer_taxpayer_type = fields.Selection(
        [
            ("1", "Physical Person"),
            ("2", "Legal Entity"),
        ],
        string="Issuer Taxpayer Type",
        copy=False,
    )
    py_document_number = fields.Char(
        string="Document Number",
        copy=False,
        index=True,
    )
    py_full_number = fields.Char(
        string="Full Number",
        copy=False,
        index=True,
    )
    py_emission_type = fields.Selection(
        [
            ("1", "Normal"),
            ("2", "Contingency"),
        ],
        string="Emission Type",
        default="1",
        copy=False,
    )
    py_cod_seg = fields.Char(
        string="Security Code",
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
        string="Receiver Nature",
        copy=False,
        help="Receiver fiscal nature for the Paraguay payload: taxpayer or non-taxpayer.",
    )
    py_receiver_taxpayer_type = fields.Selection(
        [
            ("1", "Physical Person"),
            ("2", "Legal Entity"),
        ],
        string="Receiver Taxpayer Type",
        copy=False,
        help="Receiver taxpayer type for later SIFEN iTiContRec mapping.",
    )
    py_receiver_operation_type = fields.Selection(
        [
            ("1", "B2B"),
            ("2", "B2C"),
            ("3", "B2G"),
            ("4", "B2F"),
        ],
        string="Receiver Operation Type",
        copy=False,
        # Compatibility note: older Stage 5.5 data exposed "3" as Foreign.
        # Stage 6.5.2B-2 aligns labels with SIFEN but does not migrate or
        # reinterpret existing stored values; integrations should review
        # historical "3" values before using them for schema-ready XML.
        help="SIFEN receiver operation type: B2B, B2C, B2G, or B2F.",
    )
    py_receiver_id_type = fields.Selection(
        [
            ("1", "Paraguayan ID"),
            ("2", "Passport"),
            ("3", "Foreign ID"),
            ("4", "Residence Card"),
            ("5", "Unnamed"),
            ("6", "Diplomatic Tax Exemption Card"),
            ("9", "Other"),
        ],
        string="Receiver ID Type",
        copy=False,
        help="Receiver identity document type for non-taxpayer SIFEN receiver data.",
    )
    py_receiver_id_type_description = fields.Char(
        string="Receiver ID Type Description",
        copy=False,
        help="Description for the receiver identity document type, such as Cedula paraguaya.",
    )
    py_receiver_id_number = fields.Char(
        string="Receiver ID Number",
        copy=False,
        help="Receiver identity document number for non-taxpayer SIFEN receiver data.",
    )
    py_receiver_country_code = fields.Char(
        string="Receiver Country",
        default="PRY",
        copy=False,
        help="ISO-style receiver country code used in the Paraguay payload. Use PRY for Paraguay.",
    )
    py_receiver_country_description = fields.Char(
        string="Receiver Country Description",
        default="Paraguay",
        copy=False,
        help="Receiver country description for later SIFEN receiver geography mapping.",
    )
    py_receiver_address = fields.Text(
        string="Receiver Address",
        copy=False,
        help="Receiver address included in the normalized Paraguay payload.",
    )
    py_receiver_house_number = fields.Char(
        string="Receiver House Number",
        default="0",
        copy=False,
        help="Receiver house number for later SIFEN receiver geography mapping. Use 0 when not available.",
    )
    py_receiver_phone = fields.Char(
        string="Receiver Phone",
        copy=False,
        help="Receiver phone included in the normalized Paraguay payload when available.",
    )
    py_receiver_department_code = fields.Char(
        string="Receiver Department Code",
        copy=False,
        help="Receiver department code for later SIFEN receiver geography mapping.",
    )
    py_receiver_department_name = fields.Char(
        string="Receiver Department Name",
        copy=False,
        help="Receiver department name for later SIFEN receiver geography mapping.",
    )
    py_receiver_district_code = fields.Char(
        string="Receiver District Code",
        copy=False,
        help="Receiver district code for later SIFEN receiver geography mapping.",
    )
    py_receiver_district_name = fields.Char(
        string="Receiver District Name",
        copy=False,
        help="Receiver district name for later SIFEN receiver geography mapping.",
    )
    py_receiver_city_code = fields.Char(
        string="Receiver City Code",
        copy=False,
        help="Receiver city code for later SIFEN receiver geography mapping.",
    )
    py_receiver_city_name = fields.Char(
        string="Receiver City Name",
        copy=False,
        help="Receiver city name for later SIFEN receiver geography mapping.",
    )
    py_receiver_customer_code = fields.Char(
        string="Receiver Customer Code",
        copy=False,
        help="Customer code snapshot for later SIFEN receiver data mapping.",
    )
    py_transaction_type_code = fields.Selection(
        [
            ("1", "Sale of goods"),
            ("2", "Service provision"),
        ],
        string="Transaction Type",
        default="2",
        copy=False,
        help="Transaction type used in the Paraguay payload. Default is service provision.",
    )
    py_tax_type_code = fields.Selection(
        [
            ("1", "IVA"),
            ("4", "None"),
        ],
        string="Tax Type",
        default="1",
        copy=False,
        help="Tax type used in the Paraguay payload. Use IVA for normal taxed invoices.",
    )
    py_currency = fields.Char(
        string="Fiscal Currency",
        default="PYG",
        copy=False,
        help="Currency code used in the Paraguay payload. Default is PYG.",
    )
    py_exchange_rate = fields.Float(
        string="Exchange Rate",
        copy=False,
        help="Exchange rate required when the Paraguay payload currency is not PYG.",
    )
    py_sale_condition_code = fields.Selection(
        [
            ("1", "Cash"),
            ("2", "Credit"),
        ],
        string="Sale Condition",
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
        string="Payment Type",
        default="1",
        copy=False,
        help="Payment method for the Paraguay payload, such as cash or bank transfer.",
    )
    py_payment_amount = fields.Monetary(
        string="Payment Amount",
        currency_field="currency_id",
        copy=False,
        help="Payment amount to include in the Paraguay payload. Defaults to document total if empty.",
    )
    py_payment_currency = fields.Char(
        string="Payment Currency",
        default="PYG",
        copy=False,
        help="Payment currency code used in the Paraguay payload. Default is PYG.",
    )

    def action_download_paraguay_kude(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/einvoice_py/delivery/{self.uuid}/pdf",
            "target": "self",
        }

    def action_download_paraguay_xml(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/einvoice_py/delivery/{self.uuid}/xml",
            "target": "self",
        }
