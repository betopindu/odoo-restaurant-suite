from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    py_sifen_receiver_profile = fields.Selection(
        [("taxpayer", "Paraguay Taxpayer (B2B)"), ("unnamed_consumer", "Unnamed Consumer (B2C)")],
        string="SIFEN Receiver Profile",
    )
    py_sifen_taxpayer_type = fields.Selection(
        [("1", "Physical Person"), ("2", "Legal Entity")], string="SIFEN Taxpayer Type"
    )
    py_sifen_ruc_resolution = fields.Selection(
        [
            ("authority", "SIFEN Consulta RUC"),
            ("manual_unverified", "Manual, unverified"),
        ],
        string="RUC Resolution",
        copy=False,
        readonly=True,
    )
    py_sifen_ruc_status_code = fields.Char(copy=False, readonly=True)
    py_sifen_ruc_status = fields.Char(copy=False, readonly=True)
    py_sifen_ruc_electronic_issuer = fields.Char(copy=False, readonly=True)
    py_sifen_ruc_checked_at = fields.Datetime(copy=False, readonly=True)
    py_sifen_house_number = fields.Char(string="SIFEN House Number")
    py_sifen_department_code = fields.Char(string="SIFEN Department Code")
    py_sifen_department_name = fields.Char(string="SIFEN Department")
    py_sifen_district_code = fields.Char(string="SIFEN District Code")
    py_sifen_district_name = fields.Char(string="SIFEN District")
    py_sifen_city_code = fields.Char(string="SIFEN City Code")
    py_sifen_city_name = fields.Char(string="SIFEN City")
    py_sifen_self_invoice_seller_nature = fields.Selection(
        [("1", "Non-taxpayer"), ("2", "Foreign")],
        string="SIFEN Self-Invoice Seller Nature",
    )
    py_sifen_self_invoice_id_type = fields.Selection(
        [("1", "Paraguayan ID"), ("2", "Passport"), ("3", "Foreign ID"), ("4", "Residence Card")],
        string="SIFEN Self-Invoice Seller ID Type",
    )
