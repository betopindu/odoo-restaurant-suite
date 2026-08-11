from odoo import fields, models
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = "account.move"

    fiscal_document_ids = fields.One2many(
        "fiscal.document",
        "account_move_id",
        string="Fiscal Documents",
        readonly=True,
    )
    fiscal_document_count = fields.Integer(
        compute="_compute_fiscal_document_count",
    )

    def _compute_fiscal_document_count(self):
        grouped = self.env["fiscal.document"]._read_group(
            [("account_move_id", "in", self.ids)],
            ["account_move_id"],
            ["__count"],
        ) if self.ids else []
        counts = {move.id: count for move, count in grouped}
        for move in self:
            move.fiscal_document_count = counts.get(move.id, 0)

    def action_open_fiscal_documents(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "einvoice_module.action_fiscal_document"
        )
        action["domain"] = [("account_move_id", "=", self.id)]
        if self.fiscal_document_count == 1:
            action.update({
                "view_mode": "form",
                "res_id": self.fiscal_document_ids.id,
                "views": [(False, "form")],
            })
        return action

    def _check_fiscal_source_mutation(self):
        protected = self.env["fiscal.document"].sudo().search_count([
            ("account_move_id", "in", self.ids),
            ("active", "=", True),
        ])
        if protected:
            raise ValidationError(
                "This invoice has a fiscal snapshot. Fiscal correction must be "
                "resolved before resetting or cancelling the accounting invoice."
            )

    def write(self, values):
        fiscal_source_fields = {
            "partner_id", "currency_id", "invoice_date", "invoice_line_ids",
        }
        if fiscal_source_fields.intersection(values):
            self._check_fiscal_source_mutation()
        return super().write(values)

    def button_draft(self):
        self._check_fiscal_source_mutation()
        return super().button_draft()

    def button_cancel(self):
        self._check_fiscal_source_mutation()
        return super().button_cancel()
