from odoo import fields, models


FISCAL_DOCUMENT_STATE_SELECTION = [
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
]


class FiscalDocumentLockPolicy(models.Model):
    _name = "fiscal.document.lock.policy"
    _description = "Fiscal Document Lock Policy"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        "fiscal.document.lock.policy.line",
        "policy_id",
        string="Locked States",
    )
    allow_admin_override = fields.Boolean(default=True)
    description = fields.Text()


class FiscalDocumentLockPolicyLine(models.Model):
    _name = "fiscal.document.lock.policy.line"
    _description = "Fiscal Document Lock Policy Line"
    _order = "policy_id, state"
    _sql_constraints = [
        (
            "policy_state_unique",
            "unique(policy_id, state)",
            "Each locked state can only be configured once per policy.",
        ),
    ]

    policy_id = fields.Many2one(
        "fiscal.document.lock.policy",
        required=True,
        ondelete="cascade",
        index=True,
    )
    state = fields.Selection(
        FISCAL_DOCUMENT_STATE_SELECTION,
        required=True,
        index=True,
    )
