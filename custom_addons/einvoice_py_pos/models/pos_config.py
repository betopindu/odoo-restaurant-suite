from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PosConfig(models.Model):
    _inherit = "pos.config"

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

    @api.constrains(
        "py_fiscal_checkout_enabled",
        "py_fiscal_environment",
        "py_fiscal_tenant_id",
        "py_fiscal_establishment_id",
        "py_fiscal_point_of_issue_id",
        "py_fiscal_unnamed_partner_id",
        "company_id",
    )
    def _check_py_fiscal_checkout_scope(self):
        for config in self.filtered("py_fiscal_checkout_enabled"):
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
