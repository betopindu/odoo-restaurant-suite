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
