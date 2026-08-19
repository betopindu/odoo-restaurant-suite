import json

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class FiscalDocument(models.Model):
    _inherit = "fiscal.document"

    py_establishment_id = fields.Many2one(
        "fiscal.py.establishment",
        string="Establishment",
        copy=False,
    )
    py_point_of_issue_id = fields.Many2one(
        "fiscal.py.point.of.issue",
        string="Point of Issue",
        copy=False,
    )
    py_timbrado_id = fields.Many2one(
        "fiscal.py.timbrado",
        string="Timbrado",
        copy=False,
    )
    py_csc_id = fields.Many2one(
        "fiscal.py.csc",
        string="CSC",
        copy=False,
    )
    py_issuer_id = fields.Many2one(
        "fiscal.py.issuer",
        string="Issuer",
        copy=False,
    )
    py_issuer_ruc = fields.Char(
        string="Issuer RUC",
        copy=False,
    )
    py_issuer_ruc_dv = fields.Char(
        string="Issuer RUC DV",
        copy=False,
    )
    py_issuer_taxpayer_type = fields.Selection(
        [
            ("1", "Physical Person"),
            ("2", "Legal Entity"),
        ],
        string="Issuer Taxpayer Type",
        copy=False,
    )
    py_document_number = fields.Char(
        string="Document Number",
        copy=False,
        index=True,
    )
    py_full_number = fields.Char(
        string="Full Number",
        copy=False,
        index=True,
    )
    py_emission_type = fields.Selection(
        [
            ("1", "Normal"),
            ("2", "Contingency"),
        ],
        string="Emission Type",
        default="1",
        copy=False,
    )
    py_cod_seg = fields.Char(
        string="Security Code",
        copy=False,
    )
    py_cdc_base = fields.Char(
        string="Paraguay CDC Base",
        copy=False,
        index=True,
    )
    py_cdc_dv = fields.Char(
        string="Paraguay CDC DV",
        copy=False,
    )
    py_cdc = fields.Char(
        string="Paraguay CDC",
        copy=False,
        index=True,
    )
    py_receiver_nature = fields.Selection(
        [
            ("1", "Taxpayer"),
            ("2", "Non-taxpayer"),
        ],
        string="Receiver Nature",
        copy=False,
        help="Receiver fiscal nature for the Paraguay payload: taxpayer or non-taxpayer.",
    )
    py_receiver_taxpayer_type = fields.Selection(
        [
            ("1", "Physical Person"),
            ("2", "Legal Entity"),
        ],
        string="Receiver Taxpayer Type",
        copy=False,
        help="Receiver taxpayer type for later SIFEN iTiContRec mapping.",
    )
    py_receiver_operation_type = fields.Selection(
        [
            ("1", "B2B"),
            ("2", "B2C"),
            ("3", "B2G"),
            ("4", "B2F"),
        ],
        string="Receiver Operation Type",
        copy=False,
        # Compatibility note: older Stage 5.5 data exposed "3" as Foreign.
        # Stage 6.5.2B-2 aligns labels with SIFEN but does not migrate or
        # reinterpret existing stored values; integrations should review
        # historical "3" values before using them for schema-ready XML.
        help="SIFEN receiver operation type: B2B, B2C, B2G, or B2F.",
    )
    py_receiver_id_type = fields.Selection(
        [
            ("1", "Paraguayan ID"),
            ("2", "Passport"),
            ("3", "Foreign ID"),
            ("4", "Residence Card"),
            ("5", "Unnamed"),
            ("6", "Diplomatic Tax Exemption Card"),
            ("9", "Other"),
        ],
        string="Receiver ID Type",
        copy=False,
        help="Receiver identity document type for non-taxpayer SIFEN receiver data.",
    )
    py_receiver_id_type_description = fields.Char(
        string="Receiver ID Type Description",
        copy=False,
        help="Description for the receiver identity document type, such as Cedula paraguaya.",
    )
    py_receiver_id_number = fields.Char(
        string="Receiver ID Number",
        copy=False,
        help="Receiver identity document number for non-taxpayer SIFEN receiver data.",
    )
    py_receiver_country_code = fields.Char(
        string="Receiver Country",
        default="PRY",
        copy=False,
        help="ISO-style receiver country code used in the Paraguay payload. Use PRY for Paraguay.",
    )
    py_receiver_country_description = fields.Char(
        string="Receiver Country Description",
        default="Paraguay",
        copy=False,
        help="Receiver country description for later SIFEN receiver geography mapping.",
    )
    py_receiver_address = fields.Text(
        string="Receiver Address",
        copy=False,
        help="Receiver address included in the normalized Paraguay payload.",
    )
    py_receiver_house_number = fields.Char(
        string="Receiver House Number",
        default="0",
        copy=False,
        help="Receiver house number for later SIFEN receiver geography mapping. Use 0 when not available.",
    )
    py_receiver_phone = fields.Char(
        string="Receiver Phone",
        copy=False,
        help="Receiver phone included in the normalized Paraguay payload when available.",
    )
    py_receiver_department_code = fields.Char(
        string="Receiver Department Code",
        copy=False,
        help="Receiver department code for later SIFEN receiver geography mapping.",
    )
    py_receiver_department_name = fields.Char(
        string="Receiver Department Name",
        copy=False,
        help="Receiver department name for later SIFEN receiver geography mapping.",
    )
    py_receiver_district_code = fields.Char(
        string="Receiver District Code",
        copy=False,
        help="Receiver district code for later SIFEN receiver geography mapping.",
    )
    py_receiver_district_name = fields.Char(
        string="Receiver District Name",
        copy=False,
        help="Receiver district name for later SIFEN receiver geography mapping.",
    )
    py_receiver_city_code = fields.Char(
        string="Receiver City Code",
        copy=False,
        help="Receiver city code for later SIFEN receiver geography mapping.",
    )
    py_receiver_city_name = fields.Char(
        string="Receiver City Name",
        copy=False,
        help="Receiver city name for later SIFEN receiver geography mapping.",
    )
    py_receiver_customer_code = fields.Char(
        string="Receiver Customer Code",
        copy=False,
        help="Customer code snapshot for later SIFEN receiver data mapping.",
    )
    py_transaction_type_code = fields.Selection(
        [
            ("1", "Sale of goods"),
            ("2", "Service provision"),
        ],
        string="Transaction Type",
        default="2",
        copy=False,
        help="Transaction type used in the Paraguay payload. Default is service provision.",
    )
    py_tax_type_code = fields.Selection(
        [
            ("1", "IVA"),
            ("4", "None"),
        ],
        string="Tax Type",
        default="1",
        copy=False,
        help="Tax type used in the Paraguay payload. Use IVA for normal taxed invoices.",
    )
    py_currency = fields.Char(
        string="Fiscal Currency",
        default="PYG",
        copy=False,
        help="Currency code used in the Paraguay payload. Default is PYG.",
    )
    py_exchange_rate = fields.Float(
        string="Exchange Rate",
        copy=False,
        help="Exchange rate required when the Paraguay payload currency is not PYG.",
    )
    py_sale_condition_code = fields.Selection(
        [
            ("1", "Cash"),
            ("2", "Credit"),
        ],
        string="Sale Condition",
        default="1",
        copy=False,
        help="Sale condition for the Paraguay payload: cash or credit.",
    )
    py_payment_type_code = fields.Selection(
        [
            ("1", "Cash"),
            ("3", "Credit card"),
            ("5", "Bank transfer"),
            ("17", "Mobile payment"),
        ],
        string="Payment Type",
        default="1",
        copy=False,
        help="Payment method for the Paraguay payload, such as cash or bank transfer.",
    )
    py_payment_amount = fields.Monetary(
        string="Payment Amount",
        currency_field="currency_id",
        copy=False,
        help="Payment amount to include in the Paraguay payload. Defaults to document total if empty.",
    )
    py_payment_currency = fields.Char(
        string="Payment Currency",
        default="PYG",
        copy=False,
        help="Payment currency code used in the Paraguay payload. Default is PYG.",
    )
    py_last_transmission_id = fields.Many2one(
        "fiscal.transmission", compute="_compute_py_operator_status", string="Last SIFEN Attempt"
    )
    py_last_authority_code = fields.Char(compute="_compute_py_operator_status")
    py_last_authority_message = fields.Text(compute="_compute_py_operator_status")
    py_last_http_status = fields.Integer(compute="_compute_py_operator_status")
    py_last_duration_ms = fields.Integer(compute="_compute_py_operator_status")
    py_last_ambiguous = fields.Boolean(compute="_compute_py_operator_status")
    py_operator_action_state = fields.Selection(
        [
            ("submit_ready", "Ready for Submission"),
            ("consulta_required", "Consulta DE Required"),
            ("manual_retry_allowed", "Manual Retry Allowed"),
            ("blocked", "Blocked"),
        ],
        compute="_compute_py_operator_status",
    )
    py_operator_guidance = fields.Char(compute="_compute_py_operator_status")

    @api.depends(
        "state",
        "country_code",
        "country_identifier",
        "transmission_ids.state",
        "transmission_ids.authority_status_code",
        "transmission_ids.authority_message",
        "transmission_ids.error_code",
        "transmission_ids.metadata_json",
    )
    def _compute_py_operator_status(self):
        from odoo.addons.einvoice_py.services.py_sifen_operator_service import (
            PySifenOperatorService,
        )

        service = PySifenOperatorService(self.env)
        for document in self:
            latest = document.transmission_ids.sorted(
                key=lambda item: (
                    item.started_at
                    or fields.Datetime.from_string("1970-01-01 00:00:00"),
                    item.id,
                ),
                reverse=True,
            )[:1]
            document.py_last_transmission_id = latest
            document.py_last_authority_code = latest.authority_status_code if latest else False
            document.py_last_authority_message = latest.authority_message if latest else False
            document.py_last_http_status = latest.http_status if latest else 0
            document.py_last_duration_ms = latest.duration_ms if latest else 0
            document.py_last_ambiguous = self._py_transmission_is_ambiguous(latest)
            if (document.country_code or "").upper() == "PY":
                state, guidance = service.guidance(document=document)
            else:
                state, guidance = "blocked", "Not a Paraguay fiscal document."
            document.py_operator_action_state = state
            document.py_operator_guidance = guidance

    @staticmethod
    def _py_transmission_is_ambiguous(transmission):
        if not transmission:
            return False
        try:
            metadata = json.loads(transmission.metadata_json or "{}")
        except (TypeError, ValueError):
            metadata = {}
        return bool(
            transmission.error_code == "ambiguous_submission"
            or metadata.get("ambiguous") is True
        )

    def _py_require_operator(self):
        if not self.env.user.has_group("einvoice_py.group_py_fiscal_operator"):
            raise AccessError("Only an authorized fiscal operator may contact SIFEN.")

    def _py_operator_wizard(self, operation):
        self.ensure_one()
        self._py_require_operator()
        if operation == "submit":
            if self.py_operator_action_state not in ("submit_ready", "manual_retry_allowed"):
                raise ValidationError("This document is not eligible for operator submission.")
            if self.py_operator_action_state == "manual_retry_allowed":
                wizard_operation = "manual_retry"
                warning = (
                    "Confirming performs exactly one manual retry of this electronic "
                    "document using its current CDC. Automatic submission and retry "
                    "remain disabled."
                )
            else:
                wizard_operation = "submit"
                warning = (
                    "Confirming performs exactly one SIFEN submission for this electronic "
                    "document. Automatic submission and retry remain disabled."
                )
        elif operation == "reconcile":
            if self.py_operator_action_state != "consulta_required":
                raise ValidationError("This document is not eligible for Consulta DE recovery.")
            wizard_operation = "reconcile"
            warning = (
                "This confirmation performs exactly one Consulta DE for the current CDC. "
                "It does not resend the electronic document."
            )
        else:
            raise ValidationError("Unsupported SIFEN operator operation.")
        wizard = self.env["py.sifen.operator.wizard"].create({
            "document_id": self.id,
            "operation": wizard_operation,
            "warning": warning,
        })
        return {
            "type": "ir.actions.act_window",
            "name": "Confirm SIFEN Operation",
            "res_model": "py.sifen.operator.wizard",
            "view_mode": "form",
            "res_id": wizard.id,
            "target": "new",
        }

    def action_open_py_sifen_submission(self):
        return self._py_operator_wizard("submit")

    def action_open_py_sifen_reconciliation(self):
        return self._py_operator_wizard("reconcile")

    def action_check_py_sifen_readiness(self):
        from odoo.addons.einvoice_py.services.py_sifen_test_readiness_service import (
            PySifenTestReadinessService,
        )

        self.ensure_one()
        self._py_require_operator()
        report = PySifenTestReadinessService(self.env).check(document=self)
        if report.get("ready"):
            message = "Fiscal configuration, credential scope and certificate are ready."
            notification_type = "success"
        else:
            message = " ".join(report.get("errors") or ["Readiness validation failed."])
            notification_type = "warning"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": f"SIFEN readiness: {report.get('status') or 'unknown'}",
                "message": message,
                "type": notification_type,
                "sticky": True,
            },
        }

    def action_download_paraguay_kude(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/einvoice_py/delivery/{self.uuid}/pdf",
            "target": "self",
        }

    def action_download_paraguay_xml(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/einvoice_py/delivery/{self.uuid}/xml",
            "target": "self",
        }

    def action_preview_paraguay_kude(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/einvoice_py/preview/{self.uuid}/kude",
            "target": "self",
        }
