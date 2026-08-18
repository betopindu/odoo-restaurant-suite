from odoo import api, fields, models
from odoo.exceptions import ValidationError


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
    py_fiscal_document_id = fields.Many2one(
        "fiscal.document",
        compute="_compute_py_fiscal_ui_state",
        string="Paraguay Fiscal Document",
    )
    py_fiscal_document_state = fields.Selection(
        selection=lambda self: self.env["fiscal.document"]._fields["state"].selection,
        compute="_compute_py_fiscal_ui_state",
        string="Paraguay Fiscal Status",
    )

    @api.depends(
        "fiscal_document_ids.state",
        "fiscal_document_ids.active",
        "fiscal_document_ids.country_code",
    )
    def _compute_py_fiscal_ui_state(self):
        for move in self:
            documents = move.fiscal_document_ids.filtered(
                lambda item: item.active and (item.country_code or "").upper() == "PY"
            )
            move.py_fiscal_document_id = documents[:1]
            move.py_fiscal_document_state = documents[:1].state or False

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

    def action_open_paraguay_sifen_submission(self):
        self.ensure_one()
        documents = self.fiscal_document_ids.filtered(
            lambda item: item.active and (item.country_code or "").upper() == "PY"
        )
        if len(documents) != 1:
            raise ValidationError(
                "SIFEN submission requires exactly one active Paraguay fiscal document."
            )
        return documents.action_open_py_sifen_submission()
