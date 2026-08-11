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
    py_sifen_house_number = fields.Char(string="SIFEN House Number")
    py_sifen_department_code = fields.Char(string="SIFEN Department Code")
    py_sifen_department_name = fields.Char(string="SIFEN Department")
    py_sifen_district_code = fields.Char(string="SIFEN District Code")
    py_sifen_district_name = fields.Char(string="SIFEN District")
    py_sifen_city_code = fields.Char(string="SIFEN City Code")
    py_sifen_city_name = fields.Char(string="SIFEN City")
