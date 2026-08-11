from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    py_fiscal_environment = fields.Selection(
        [("test", "SIFEN TEST"), ("production", "SIFEN Production")],
        string="SIFEN Environment", default="test", copy=False,
    )
    py_fiscal_tenant_id = fields.Many2one("fiscal.tenant", string="Fiscal Tenant", copy=False)
    py_fiscal_establishment_id = fields.Many2one(
        "fiscal.py.establishment", string="SIFEN Establishment", copy=False
    )
    py_fiscal_point_of_issue_id = fields.Many2one(
        "fiscal.py.point.of.issue", string="SIFEN Point of Issue", copy=False
    )
    py_sale_condition_code = fields.Selection(
        [("1", "Cash"), ("2", "Credit")], string="SIFEN Sale Condition", default="1", copy=False
    )

    def action_prepare_paraguay_fiscal_document(self):
        from odoo.addons.einvoice_py.services.py_account_move_integration_service import (
            PyFiscalDocumentFromAccountMoveService,
        )

        self.ensure_one()
        document = PyFiscalDocumentFromAccountMoveService(self.env).create(move=self)
        return {
            "type": "ir.actions.act_window", "res_model": "fiscal.document",
            "view_mode": "form", "views": [(False, "form")],
            "res_id": document.id, "target": "current",
        }
