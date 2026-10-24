from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PosConfig(models.Model):
    _inherit = "pos.config"

    PY_SIFEN_SUPPORTED_POS_PAYMENT_TYPES = {"1", "3", "4", "5", "7", "17", "21"}

    py_fiscal_checkout_enabled = fields.Boolean(
        string="Paraguay fiscal checkout",
        help="Enables the optional POS channel without coupling the fiscal engine to POS or KDS.",
    )
    py_fiscal_allow_no_fe = fields.Boolean(
        string="Allow sale without FE",
        default=True,
        help="Allows an explicitly non-fiscal Odoo receipt without creating a CDC or contacting SIFEN.",
    )
    py_fiscal_environment = fields.Selection(
        [("test", "SIFEN TEST"), ("production", "SIFEN Production")],
        string="SIFEN environment",
        default="test",
    )
    py_fiscal_tenant_id = fields.Many2one(
        "fiscal.tenant",
        string="Fiscal tenant",
        ondelete="restrict",
    )
    py_fiscal_establishment_id = fields.Many2one(
        "fiscal.py.establishment",
        string="SIFEN establishment",
        ondelete="restrict",
    )
    py_fiscal_point_of_issue_id = fields.Many2one(
        "fiscal.py.point.of.issue",
        string="SIFEN point of issue",
        ondelete="restrict",
    )
    py_fiscal_unnamed_partner_id = fields.Many2one(
        "res.partner",
        string="Unnamed consumer",
        ondelete="restrict",
        help="Internal partner used only to create the accounting invoice for an innominado FE.",
    )
    py_fiscal_auto_submit_enabled = fields.Boolean(
        string="Submit FE after POS payment",
        help=(
            "Queues exactly one SIFEN submission after the POS invoice and fiscal "
            "document are prepared. Automatic retries remain disabled."
        ),
    )
    py_fiscal_auto_submit_user_id = fields.Many2one(
        "res.users",
        string="Fiscal submission operator",
        ondelete="restrict",
        help="Authorized fiscal operator recorded as the actor of automatic POS submissions.",
    )

    @api.constrains(
        "py_fiscal_checkout_enabled",
        "py_fiscal_environment",
        "py_fiscal_tenant_id",
        "py_fiscal_establishment_id",
        "py_fiscal_point_of_issue_id",
        "py_fiscal_unnamed_partner_id",
        "py_fiscal_auto_submit_enabled",
        "py_fiscal_auto_submit_user_id",
        "payment_method_ids",
        "company_id",
    )
    def _check_py_fiscal_checkout_scope(self):
        for config in self:
            if config.py_fiscal_auto_submit_enabled and not config.py_fiscal_checkout_enabled:
                raise ValidationError(
                    "Automatic POS fiscal submission requires Paraguay fiscal checkout."
                )
            if not config.py_fiscal_checkout_enabled:
                continue
            required = {
                "fiscal tenant": config.py_fiscal_tenant_id,
                "establishment": config.py_fiscal_establishment_id,
                "point of issue": config.py_fiscal_point_of_issue_id,
                "unnamed consumer": config.py_fiscal_unnamed_partner_id,
            }
            missing = [label for label, value in required.items() if not value]
            if missing:
                raise ValidationError(
                    "Paraguay POS fiscal checkout is incomplete: " + ", ".join(missing) + "."
                )
            establishment = config.py_fiscal_establishment_id
            point = config.py_fiscal_point_of_issue_id
            if (
                config.py_fiscal_tenant_id.company_id != config.company_id
                or establishment.tenant_id != config.py_fiscal_tenant_id
                or establishment.company_id != config.company_id
                or point.establishment_id != establishment
            ):
                raise ValidationError(
                    "Paraguay POS fiscal checkout tenant, company, establishment and point of issue must share one scope."
                )
            issuer = establishment.issuer_id
            if not issuer or issuer.environment != config.py_fiscal_environment:
                raise ValidationError(
                    "Paraguay POS fiscal checkout environment must match the establishment issuer."
                )
            if config.py_fiscal_unnamed_partner_id.py_sifen_receiver_profile != "unnamed_consumer":
                raise ValidationError(
                    "Paraguay POS unnamed consumer must use the unnamed SIFEN receiver profile."
                )
            unmapped = config.payment_method_ids.filtered(
                lambda method: not method.py_sifen_payment_type_code
            )
            if unmapped:
                raise ValidationError(
                    "Paraguay fiscal checkout requires a SIFEN payment type for: "
                    + ", ".join(unmapped.mapped("name"))
                    + "."
                )
            unsupported = config.payment_method_ids.filtered(
                lambda method: method.py_sifen_payment_type_code
                not in self.PY_SIFEN_SUPPORTED_POS_PAYMENT_TYPES
            )
            if unsupported:
                raise ValidationError(
                    "Paraguay fiscal checkout does not support the configured SIFEN "
                    "payment detail for: " + ", ".join(unsupported.mapped("name")) + "."
                )
            incomplete_cards = config.payment_method_ids.filtered(
                lambda method: method.py_sifen_payment_type_code in ("3", "4")
                and not method._py_sifen_card_snapshot()
            )
            if incomplete_cards:
                raise ValidationError(
                    "Paraguay fiscal card methods require brand, processing method and "
                    "a complete processor identity when provided: "
                    + ", ".join(incomplete_cards.mapped("name"))
                    + "."
                )
            if config.py_fiscal_auto_submit_enabled:
                operator = config.py_fiscal_auto_submit_user_id
                if not operator:
                    raise ValidationError(
                        "Automatic POS fiscal submission requires an authorized operator."
                    )
                if not operator.has_group("einvoice_py.group_py_fiscal_operator"):
                    raise ValidationError(
                        "The automatic POS fiscal submission user must be a Paraguay Fiscal Operator."
                    )
                if config.company_id not in operator.company_ids:
                    raise ValidationError(
                        "The automatic POS fiscal operator must have access to the POS company."
                    )
                if config.py_fiscal_tenant_id not in operator.allowed_fiscal_tenant_ids:
                    raise ValidationError(
                        "The automatic POS fiscal operator must have access to the fiscal tenant."
                    )
