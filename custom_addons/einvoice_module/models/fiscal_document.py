from uuid import uuid4

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_module.services.idempotency import FiscalIdempotencyService
from odoo.addons.einvoice_module.services.orchestrator import FiscalOrchestrator


LOCKED_FISCAL_STATES = {
    "submitted",
    "accepted",
    "cancelled",
    "failed_final",
    "manual_review",
}
FISCAL_LOCK_BYPASS_CONTEXT = "einvoice_skip_fiscal_document_lock"
FISCAL_CREATION_ACTOR_CONTEXT = "einvoice_creation_actor_context"


class FiscalDocument(models.Model):
    _name = "fiscal.document"
    _description = "Fiscal Document"
    _order = "create_date desc, id desc"

    name = fields.Char(default="/", copy=False, index=True)
    uuid = fields.Char(default=lambda self: str(uuid4()), required=True, copy=False, index=True)
    active = fields.Boolean(default=True)

    tenant_id = fields.Many2one("fiscal.tenant", required=True, index=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    adapter_config_id = fields.Many2one("fiscal.adapter.config")

    document_type = fields.Selection(
        [
            ("invoice", "Invoice"),
            ("credit_note", "Credit Note"),
            ("debit_note", "Debit Note"),
            ("receipt", "Receipt"),
        ],
        required=True,
        default="invoice",
        index=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("ready", "Ready"),
            ("validation_error", "Validation Error"),
            ("queued", "Queued"),
            ("signed", "Signed"),
            ("submitted", "Submitted"),
            ("accepted", "Accepted"),
            ("rejected", "Rejected"),
            ("failed_retryable", "Failed Retryable"),
            ("failed_final", "Failed Final"),
            ("cancelled", "Cancelled"),
            ("manual_review", "Manual Review"),
        ],
        default="draft",
        required=True,
        index=True,
    )

    country_code = fields.Char(size=2, index=True)
    environment = fields.Selection(
        [("test", "Test"), ("production", "Production")],
        default="test",
        required=True,
    )
    adapter_code = fields.Char(index=True)

    source_system = fields.Char(index=True)
    source_model = fields.Char(index=True)
    source_res_id = fields.Integer(index=True)
    source_external_id = fields.Char(index=True)
    source_reference = fields.Char(index=True)
    idempotency_key = fields.Char(copy=False, index=True)

    fiscal_number = fields.Char(index=True)
    fiscal_series = fields.Char(index=True)
    country_identifier = fields.Char(index=True)
    authority_status = fields.Char(index=True)
    authority_receipt_ref = fields.Char(index=True)

    partner_id = fields.Many2one("res.partner")
    customer_name = fields.Char()
    customer_tax_id = fields.Char(index=True)
    customer_tax_id_type = fields.Char()
    customer_email = fields.Char()

    issue_datetime = fields.Datetime()
    submitted_at = fields.Datetime()
    accepted_at = fields.Datetime()
    rejected_at = fields.Datetime()
    cancelled_at = fields.Datetime()

    amount_untaxed = fields.Monetary(currency_field="currency_id")
    amount_tax = fields.Monetary(currency_field="currency_id")
    amount_discount = fields.Monetary(currency_field="currency_id")
    amount_total = fields.Monetary(currency_field="currency_id")

    line_ids = fields.One2many("fiscal.document.line", "document_id")
    event_ids = fields.One2many("fiscal.event", "document_id")
    transmission_ids = fields.One2many("fiscal.transmission", "document_id")
    attachment_ids = fields.One2many("fiscal.attachment", "document_id")
    metadata_json = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        self._get_idempotency_service().ensure_unique([
            {
                "tenant_id": vals.get("tenant_id"),
                "document_type": vals.get("document_type") or "invoice",
                "idempotency_key": vals.get("idempotency_key"),
                "active": vals.get("active", True),
            }
            for vals in vals_list
        ])
        documents = super().create(vals_list)
        event_model = self.env["fiscal.event"]
        creation_actor = self.env.context.get(FISCAL_CREATION_ACTOR_CONTEXT) or {}
        actor_type = creation_actor.get("actor_type") or "user"
        if actor_type not in ("user", "system", "api"):
            actor_type = "user"
        user_id = (
            creation_actor.get("user_id") or self.env.user.id
            if actor_type == "user"
            else False
        )
        for document in documents:
            has_creation_event = any(
                event.event_type == "document_created"
                for event in document.event_ids
            )
            if has_creation_event:
                continue
            event_model.create({
                "document_id": document.id,
                "event_type": "document_created",
                "from_state": False,
                "to_state": document.state or "draft",
                "actor_type": actor_type,
                "user_id": user_id,
                "occurred_at": fields.Datetime.now(),
                "message": "Fiscal document created",
            })
        return documents

    def _is_fiscal_lock_bypassed(self):
        return (
            self.env.context.get(FISCAL_LOCK_BYPASS_CONTEXT)
            or self.env.user.has_group("base.group_system")
        )

    def _check_fiscal_edit_lock(self):
        if self._is_fiscal_lock_bypassed():
            return

        locked_documents = self.filtered(lambda document: document.state in LOCKED_FISCAL_STATES)
        if locked_documents:
            # TODO: create an audit event when administrator override auditing is introduced.
            raise ValidationError(
                "You cannot edit fiscal documents in locked states: "
                "submitted, accepted, cancelled, failed final, manual review."
            )

    def write(self, vals):
        self._check_fiscal_edit_lock()
        self._check_idempotency_write(vals)
        return super().write(vals)

    def _check_idempotency_write(self, vals):
        idempotency_fields = {"tenant_id", "document_type", "idempotency_key", "active"}
        if not idempotency_fields.intersection(vals):
            return

        self._get_idempotency_service().ensure_unique([
            {
                "tenant_id": vals.get("tenant_id", document.tenant_id.id),
                "document_type": vals.get("document_type", document.document_type),
                "idempotency_key": vals.get("idempotency_key", document.idempotency_key),
                "active": vals.get("active", document.active),
                "exclude_ids": document.ids,
            }
            for document in self
        ])

    def _get_idempotency_service(self):
        return FiscalIdempotencyService(self.env)

    def _get_orchestrator(self):
        return FiscalOrchestrator(self.env)

    def _get_user_actor_context(self):
        return {
            "actor_type": "user",
            "user_id": self.env.user.id,
        }

    def action_mark_ready(self):
        return self._get_orchestrator().mark_ready(
            self,
            actor_context=self._get_user_actor_context(),
        )

    def action_queue(self):
        return self._get_orchestrator().queue(
            self,
            actor_context=self._get_user_actor_context(),
        )

    def action_process_now(self):
        return self._get_orchestrator().process_documents(
            self,
            actor_context=self._get_user_actor_context(),
        )

    def action_retry_manual_review(self):
        return self._get_orchestrator().retry_manual_review(
            self,
            actor_context=self._get_user_actor_context(),
        )

    def action_fail_manual_review(self):
        return self._get_orchestrator().fail_manual_review(
            self,
            actor_context=self._get_user_actor_context(),
        )

    def action_cancel_manual_review(self):
        return self._get_orchestrator().cancel_manual_review(
            self,
            actor_context=self._get_user_actor_context(),
        )

    @api.model
    def cron_process_queued_documents(self, limit=10):
        return self._get_orchestrator().process_queued(limit=limit)
