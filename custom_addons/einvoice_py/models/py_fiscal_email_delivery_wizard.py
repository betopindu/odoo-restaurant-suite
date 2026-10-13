from odoo import api, fields, models

from odoo.addons.einvoice_py.services.py_fiscal_email_delivery_service import (
    PyFiscalEmailDeliveryService,
)


class PyFiscalEmailDeliveryWizard(models.TransientModel):
    _name = "py.fiscal.email.delivery.wizard"
    _description = "Paraguay Fiscal Email Delivery Confirmation"

    document_id = fields.Many2one("fiscal.document", required=True, readonly=True)
    delivery_id = fields.Many2one("py.fiscal.email.delivery", readonly=True)
    recipient_email = fields.Char(compute="_compute_context", readonly=True)
    subject = fields.Char(compute="_compute_context", readonly=True)
    warning = fields.Text(
        default=(
            "Confirming queues one email with the authoritative KuDE PDF and signed XML. "
            "It does not contact SIFEN or change the fiscal acceptance state."
        ),
        readonly=True,
    )

    @api.depends("document_id")
    def _compute_context(self):
        service = PyFiscalEmailDeliveryService(self.env)
        for wizard in self:
            if wizard.document_id:
                prepared = service.prepare(document=wizard.document_id)
                wizard.recipient_email = prepared.recipient_email
                wizard.subject = prepared.subject
            else:
                wizard.recipient_email = False
                wizard.subject = False

    def action_confirm(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM py_fiscal_email_delivery_wizard WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset(["delivery_id"])
        delivery = self.delivery_id
        if not delivery:
            delivery = PyFiscalEmailDeliveryService(self.env).enqueue(
                document=self.document_id,
                mode="manual",
            )
            self.delivery_id = delivery
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Fiscal email queued",
                "message": f"Email delivery {delivery.id} was queued for {delivery.recipient_email}.",
                "type": "success",
                "sticky": True,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }
