import re

from odoo import api, fields, models, tools
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_account_move_integration_service import (
    PyFiscalDocumentFromAccountMoveService,
)


class PosOrder(models.Model):
    _inherit = "pos.order"

    _PY_DECISION_RE = re.compile(r"[A-Za-z0-9_-]{8,64}\Z")
    _PY_FISCAL_FIELDS = {
        "py_fiscal_choice",
        "py_fiscal_decision_id",
        "py_ruc_resolution",
        "py_fiscal_delivery",
        "py_fiscal_email",
    }

    py_fiscal_choice = fields.Selection(
        [
            ("no_fe", "No FE"),
            ("consumer_final", "Consumer final"),
            ("with_ruc", "With RUC"),
        ],
        string="Paraguay fiscal choice",
        copy=False,
        index=True,
    )
    py_fiscal_decision_id = fields.Char(
        string="Fiscal decision ID",
        copy=False,
        index=True,
        readonly=True,
        help="Client-generated idempotency identity for the cashier's confirmed fiscal choice.",
    )
    py_ruc_resolution = fields.Selection(
        [
            ("not_applicable", "Not applicable"),
            ("local", "Local record"),
            ("authority", "SIFEN Consulta RUC"),
            ("manual_unverified", "Manual, unverified"),
        ],
        string="RUC resolution",
        copy=False,
        readonly=True,
    )
    py_fiscal_delivery = fields.Selection(
        [
            ("not_applicable", "Not applicable"),
            ("print", "Print"),
            ("email", "Email"),
            ("both", "Print and email"),
        ],
        string="Fiscal delivery",
        copy=False,
        readonly=True,
    )
    py_fiscal_email = fields.Char(
        string="Fiscal delivery email",
        copy=False,
        readonly=True,
    )

    _sql_constraints = [
        (
            "py_fiscal_decision_company_uniq",
            "unique(company_id, py_fiscal_decision_id)",
            "The Paraguay POS fiscal decision is already assigned to another order.",
        ),
    ]

    @api.model
    def _order_fields(self, ui_order):
        values = super()._order_fields(ui_order)
        for field_name in self._PY_FISCAL_FIELDS:
            if field_name in ui_order:
                values[field_name] = ui_order.get(field_name) or False
        return values

    @api.model
    def _export_for_ui(self, order):
        values = super()._export_for_ui(order)
        values.update({
            "py_fiscal_choice": order.py_fiscal_choice or False,
            "py_fiscal_decision_id": order.py_fiscal_decision_id or False,
            "py_ruc_resolution": order.py_ruc_resolution or False,
            "py_fiscal_delivery": order.py_fiscal_delivery or False,
            "py_fiscal_email": order.py_fiscal_email or False,
        })
        return values

    @api.model
    def create_from_ui(self, orders, draft=False):
        if not draft:
            for order in orders:
                self._validate_py_fiscal_ui_order(order.get("data") or {})
        result = super().create_from_ui(orders, draft=draft)
        if not draft:
            self._prepare_py_fiscal_documents(result)
        return result

    @api.model
    def _prepare_py_fiscal_documents(self, sync_result):
        order_ids = [item.get("id") for item in sync_result if item.get("id")]
        for order in self.browse(order_ids).exists():
            if order.py_fiscal_choice in (False, "no_fe"):
                continue
            move = order.account_move
            if not move or move.state != "posted":
                raise ValidationError(
                    "Paraguay POS fiscal preparation requires the posted Odoo invoice."
                )
            documents = move.fiscal_document_ids.filtered(
                lambda item: item.active and (item.country_code or "").upper() == "PY"
            )
            if len(documents) > 1:
                raise ValidationError(
                    "The POS invoice has multiple active Paraguay fiscal documents."
                )
            config = order.config_id
            if documents:
                document = documents
            else:
                move.write({
                    "py_fiscal_environment": config.py_fiscal_environment,
                    "py_fiscal_tenant_id": config.py_fiscal_tenant_id.id,
                    "py_fiscal_establishment_id": config.py_fiscal_establishment_id.id,
                    "py_fiscal_point_of_issue_id": config.py_fiscal_point_of_issue_id.id,
                    "py_sale_condition_code": "1",
                })
                email_requested = order.py_fiscal_delivery in ("email", "both")
                payment_snapshot = self._py_sifen_payment_snapshot(order)
                document = PyFiscalDocumentFromAccountMoveService(self.env).create(
                    move=move,
                    customer_email_override=(
                        (order.py_fiscal_email or "").strip()
                        if email_requested
                        else None
                    ),
                    email_delivery_policy=("requested" if email_requested else "suppressed"),
                    payment_snapshot=payment_snapshot,
                )
            self.env["py.pos.fiscal.submission.job"].enqueue(
                order=order,
                document=document,
            )
        return True

    @api.model
    def _py_sifen_payment_snapshot(self, order):
        grouped = {}
        for payment in order.payment_ids.sorted(lambda item: (item.payment_date, item.id)):
            if order.currency_id.is_zero(payment.amount):
                continue
            code = payment.payment_method_id.py_sifen_payment_type_code
            if not code:
                raise ValidationError(
                    "POS payment method requires a configured SIFEN payment type."
                )
            grouped[code] = grouped.get(code, 0.0) + payment.amount
        snapshot = []
        for code, amount in grouped.items():
            if order.currency_id.compare_amounts(amount, 0) <= 0:
                continue
            snapshot.append({
                "type_code": code,
                "amount": str(amount),
                "currency": order.currency_id.name,
            })
        total = sum((float(item["amount"]) for item in snapshot), 0.0)
        if not snapshot or order.currency_id.compare_amounts(total, order.amount_total) != 0:
            raise ValidationError(
                "POS payments must reconcile with the fiscal sale after change."
            )
        return snapshot

    @api.model
    def _validate_py_fiscal_ui_order(self, data):
        session = self.env["pos.session"].browse(data.get("pos_session_id")).exists()
        if not session:
            raise ValidationError("Paraguay fiscal checkout requires a valid POS session.")
        config = session.config_id
        choice = data.get("py_fiscal_choice")
        fiscal_keys_present = any(data.get(name) for name in self._PY_FISCAL_FIELDS)
        if not config.py_fiscal_checkout_enabled:
            if fiscal_keys_present:
                raise ValidationError("Paraguay fiscal checkout is disabled for this POS.")
            return True
        if choice not in ("no_fe", "consumer_final", "with_ruc"):
            raise ValidationError("Select No FE, Consumer final, or With RUC before payment.")
        decision_id = str(data.get("py_fiscal_decision_id") or "")
        if not self._PY_DECISION_RE.fullmatch(decision_id):
            raise ValidationError("Paraguay fiscal checkout requires a valid decision identity.")
        to_invoice = bool(data.get("to_invoice"))
        partner = self.env["res.partner"].browse(data.get("partner_id")).exists()
        if choice == "no_fe":
            if not config.py_fiscal_allow_no_fe:
                raise ValidationError("This POS does not allow a sale without FE.")
            if to_invoice:
                raise ValidationError("A No FE sale cannot request an Odoo invoice.")
            if data.get("py_ruc_resolution") not in (None, False, "not_applicable"):
                raise ValidationError("A No FE sale cannot contain RUC resolution evidence.")
            if data.get("py_fiscal_delivery") != "not_applicable":
                raise ValidationError("A No FE sale must not select fiscal delivery.")
            return True
        if not to_invoice or not partner:
            raise ValidationError("A fiscal POS sale requires an identified accounting invoice partner.")
        if choice == "consumer_final":
            if partner != config.py_fiscal_unnamed_partner_id:
                raise ValidationError("Consumer-final FE must use the configured unnamed consumer.")
            if data.get("py_ruc_resolution") not in (None, False, "not_applicable"):
                raise ValidationError("Consumer-final FE cannot contain RUC resolution evidence.")
        else:
            if partner.py_sifen_receiver_profile != "taxpayer":
                raise ValidationError("With-RUC FE requires a taxpayer receiver profile.")
            if data.get("py_ruc_resolution") not in ("local", "authority", "manual_unverified"):
                raise ValidationError("With-RUC FE requires an explicit RUC resolution source.")
        delivery = data.get("py_fiscal_delivery")
        if delivery not in ("print", "email", "both"):
            raise ValidationError("Paraguay fiscal delivery selection is invalid.")
        if delivery in ("email", "both"):
            email = (data.get("py_fiscal_email") or "").strip()
            if len(tools.email_split(email)) != 1:
                raise ValidationError(
                    "Email delivery requires one valid recipient email address."
                )
        return True

    def write(self, vals):
        protected = self._PY_FISCAL_FIELDS.intersection(vals)
        if protected:
            for order in self.filtered(lambda item: item.state != "draft"):
                changed = any((order[name] or False) != (vals[name] or False) for name in protected)
                if changed:
                    raise ValidationError(
                        "The confirmed Paraguay POS fiscal decision is immutable."
                    )
        return super().write(vals)
