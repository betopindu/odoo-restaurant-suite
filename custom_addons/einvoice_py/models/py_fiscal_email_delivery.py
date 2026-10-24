from odoo import api, fields, models
from odoo.exceptions import AccessError


class PyFiscalEmailDelivery(models.Model):
    _name = "py.fiscal.email.delivery"
    _description = "Paraguay Fiscal Email Delivery"
    _order = "id desc"

    document_id = fields.Many2one("fiscal.document", required=True, readonly=True, index=True)
    tenant_id = fields.Many2one("fiscal.tenant", required=True, readonly=True, index=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True, index=True)
    environment = fields.Selection(related="document_id.environment", store=True, readonly=True)
    cdc = fields.Char(required=True, readonly=True, index=True)
    recipient_email = fields.Char(readonly=True)
    sender_email = fields.Char(readonly=True)
    subject = fields.Char(readonly=True)
    mode = fields.Selection(
        [("manual", "Manual"), ("automatic", "Automatic")],
        required=True,
        readonly=True,
    )
    automatic_key = fields.Char(readonly=True, index=True, copy=False)
    request_key = fields.Char(readonly=True, index=True, copy=False)
    requested_by_id = fields.Many2one("res.users", readonly=True)
    requested_at = fields.Datetime(required=True, readonly=True)
    mail_id = fields.Many2one("mail.mail", readonly=True, ondelete="set null")
    mail_state = fields.Selection(related="mail_id.state", string="Mail State", readonly=True)
    pdf_source_attachment_id = fields.Many2one("fiscal.attachment", readonly=True)
    xml_source_attachment_id = fields.Many2one("fiscal.attachment", readonly=True)
    pdf_sha256 = fields.Char(readonly=True)
    xml_sha256 = fields.Char(readonly=True)
    preparation_status = fields.Selection(
        [("queued", "Queued"), ("failed", "Preparation Failed")],
        required=True,
        default="queued",
        readonly=True,
    )
    error_category = fields.Char(readonly=True)
    error_detail = fields.Char(readonly=True)

    _sql_constraints = [(
        "automatic_key_unique",
        "unique(automatic_key)",
        "The accepted fiscal document was already queued for automatic email delivery.",
    ), (
        "request_key_unique",
        "unique(request_key)",
        "The fiscal email delivery request was already processed.",
    )]


class FiscalDocument(models.Model):
    _inherit = "fiscal.document"

    py_email_delivery_ids = fields.One2many(
        "py.fiscal.email.delivery", "document_id", string="Email Deliveries", readonly=True
    )
    py_email_delivery_count = fields.Integer(compute="_compute_py_email_delivery_count")

    @api.depends("py_email_delivery_ids")
    def _compute_py_email_delivery_count(self):
        for document in self:
            document.py_email_delivery_count = len(document.py_email_delivery_ids)

    def action_open_py_fiscal_email_delivery(self):
        self.ensure_one()
        if not self.env.user.has_group("einvoice_py.group_py_fiscal_operator"):
            raise AccessError("Only Paraguay Fiscal Operators may email fiscal documents.")
        from odoo.addons.einvoice_py.services.py_fiscal_email_delivery_service import (
            PyFiscalEmailDeliveryService,
        )

        PyFiscalEmailDeliveryService(self.env).prepare(document=self)
        wizard = self.env["py.fiscal.email.delivery.wizard"].create({
            "document_id": self.id,
        })
        return {
            "type": "ir.actions.act_window",
            "name": "Email Authoritative Fiscal Documents",
            "res_model": "py.fiscal.email.delivery.wizard",
            "view_mode": "form",
            "res_id": wizard.id,
            "target": "new",
        }
