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
