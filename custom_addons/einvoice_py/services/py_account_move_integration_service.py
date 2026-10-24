import json
from decimal import Decimal

from psycopg2 import errors

from odoo import fields
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_module.services.account_move_integration import (
    FiscalDocumentFromAccountMoveService,
)
from odoo.addons.einvoice_py.services.cdc_service import PyCdcService
from odoo.addons.einvoice_py.services.numbering_service import PyNumberingService
from odoo.addons.einvoice_py.services.py_payload_builder import PyPayloadBuilder
from odoo.addons.einvoice_py.services.py_source_artifact_service import PySourceArtifactService


class PyFiscalDocumentFromAccountMoveService:
    """Prepare one Paraguay fiscal snapshot without signing or transmission."""

    TAX_MAPPING = {
        "iva_10": {"affectation": "1", "rate": 10.0},
        "iva_5": {"affectation": "1", "rate": 5.0},
        "exempt": {"affectation": "3", "rate": 0.0},
    }

    def __init__(self, env, *, snapshot_time_provider=None):
        self.env = env
        self.snapshot_time_provider = snapshot_time_provider or fields.Datetime.now

    def create(
        self,
        *,
        move,
        customer_email_override=None,
        email_delivery_policy="company_default",
    ):
        move.ensure_one()
        if email_delivery_policy not in ("company_default", "requested", "suppressed"):
            raise ValidationError("Unsupported Paraguay fiscal email delivery policy.")
        document_type = self._document_type(move)
        original_document = self._original_document(move, document_type)
        config = self._configuration(move, document_type)
        if move.currency_id.name != "PYG":
            raise ValidationError("Paraguay fiscal preparation currently supports PYG only.")
        self._validate_correction_note(move, document_type, original_document, config)
        if document_type == "self_invoice":
            receiver = self._receiver_values(move.company_id.partner_id.commercial_partner_id)
            # Manual Técnico v150 D202a: an Autofactura always identifies the
            # purchaser/issuer as a taxpayer receiver, but its operation type is
            # B2C rather than B2B.
            receiver["py_receiver_operation_type"] = "2"
            receiver.update(self._self_invoice_values(move))
        else:
            receiver = self._receiver_values(move.partner_id.commercial_partner_id)
        if customer_email_override is not None:
            receiver["customer_email"] = str(customer_email_override).strip()
        snapshot_at = self.snapshot_time_provider()
        document = FiscalDocumentFromAccountMoveService(
            move.with_context(fiscal_snapshot_at=snapshot_at).env
        ).create(
            move=move,
            tenant=config["tenant"],
            adapter_config=config["adapter"],
            document_values=self._document_values(
                move,
                config,
                receiver,
                snapshot_at,
                email_delivery_policy=email_delivery_policy,
            ),
            line_value_provider=self._line_values,
            document_type=document_type,
            original_document=original_document,
        )
        PyNumberingService(self.env).assign_number(document)
        PyCdcService(self.env).generate(document)
        payload = PyPayloadBuilder(self.env).build(document)
        PySourceArtifactService(self.env).persist_payload(document=document, payload=payload)
        if document.state == "draft":
            document.write({"state": "ready", "fiscal_number": document.py_full_number})
        return document

    def _document_type(self, move):
        if move.move_type == "out_invoice" and move.debit_origin_id:
            return "debit_note"
        mapping = {"out_invoice": "invoice", "out_refund": "credit_note", "in_invoice": "self_invoice"}
        document_type = mapping.get(move.move_type)
        if not document_type:
            raise ValidationError(
                "Only customer invoices, credit notes, debit notes, and vendor bills for self-invoices are supported."
            )
        return document_type

    def _self_invoice_values(self, move):
        seller = move.partner_id.commercial_partner_id
        values = {
            "py_seller_nature": seller.py_sifen_self_invoice_seller_nature,
            "py_seller_id_type": seller.py_sifen_self_invoice_id_type,
            "py_seller_id_number": seller.vat,
            "py_seller_name": seller.name,
            "py_seller_address": seller.street,
            "py_seller_house_number": seller.py_sifen_house_number,
            "py_seller_department_code": seller.py_sifen_department_code,
            "py_seller_department_name": seller.py_sifen_department_name,
            "py_seller_district_code": seller.py_sifen_district_code,
            "py_seller_district_name": seller.py_sifen_district_name,
            "py_seller_city_code": seller.py_sifen_city_code,
            "py_seller_city_name": seller.py_sifen_city_name,
            "py_transaction_address": move.py_self_invoice_transaction_address,
            "py_transaction_department_code": move.py_self_invoice_transaction_department_code,
            "py_transaction_department_name": move.py_self_invoice_transaction_department_name,
            "py_transaction_district_code": move.py_self_invoice_transaction_district_code,
            "py_transaction_district_name": move.py_self_invoice_transaction_district_name,
            "py_transaction_city_code": move.py_self_invoice_transaction_city_code,
            "py_transaction_city_name": move.py_self_invoice_transaction_city_name,
        }
        required = {
            "seller nature": values["py_seller_nature"],
            "seller ID type": values["py_seller_id_type"],
            "seller ID number": values["py_seller_id_number"],
            "seller name": values["py_seller_name"],
            "seller address": values["py_seller_address"],
            "seller house number": values["py_seller_house_number"],
            "seller department code": values["py_seller_department_code"],
            "seller department description": values["py_seller_department_name"],
            "seller city code": values["py_seller_city_code"],
            "seller city description": values["py_seller_city_name"],
            "transaction address": values["py_transaction_address"],
            "transaction department code": values["py_transaction_department_code"],
            "transaction department description": values["py_transaction_department_name"],
            "transaction city code": values["py_transaction_city_code"],
            "transaction city description": values["py_transaction_city_name"],
        }
        missing = [label for label, value in required.items() if not value]
        if values["py_seller_nature"] == "1" and (
            not seller.country_id or seller.country_id.code != "PY"
        ):
            missing.append("Paraguay seller country")
        if missing:
            raise ValidationError("Self-invoice SIFEN data is missing: " + ", ".join(missing) + ".")
        return values

    def _original_document(self, move, document_type):
        if document_type not in ("credit_note", "debit_note"):
            return self.env["fiscal.document"]
        original_move = (
            move.reversed_entry_id
            if document_type == "credit_note"
            else move.debit_origin_id
        )
        if not original_move:
            raise ValidationError(
                "Paraguay electronic credit and debit notes must be created from an original customer invoice."
            )
        documents = original_move.fiscal_document_ids.filtered(
            lambda item: item.active
            and item.document_type == "invoice"
            and (item.country_code or "").upper() == "PY"
            and item.environment == move.py_fiscal_environment
        )
        if len(documents) != 1:
            raise ValidationError(
                "The original invoice must have exactly one Paraguay fiscal document."
            )
        return documents

    def _configuration(self, move, document_type):
        tenant = move.py_fiscal_tenant_id
        if not tenant:
            tenants = self.env["fiscal.tenant"].search([
                ("active", "=", True), ("company_id", "=", move.company_id.id),
            ])
            if len(tenants) != 1:
                raise ValidationError("Select the fiscal tenant; company scope is not unambiguous.")
            tenant = tenants
        environment = move.py_fiscal_environment
        adapter = self._one("fiscal.adapter.config", [
            ("active", "=", True), ("tenant_id", "=", tenant.id),
            ("company_id", "=", move.company_id.id), ("country_code", "=", "PY"),
            ("environment", "=", environment),
        ], "Exactly one active Paraguay fiscal adapter is required.")
        issuer = self._one("fiscal.py.issuer", [
            ("active", "=", True), ("tenant_id", "=", tenant.id),
            ("company_id", "=", move.company_id.id), ("environment", "=", environment),
        ], "Exactly one active Paraguay issuer is required.")
        establishment = move.py_fiscal_establishment_id or self._one(
            "fiscal.py.establishment",
            [("active", "=", True), ("tenant_id", "=", tenant.id),
             ("company_id", "=", move.company_id.id), ("issuer_id", "=", issuer.id)],
            "Select one active Paraguay establishment.",
        )
        point = move.py_fiscal_point_of_issue_id or self._one(
            "fiscal.py.point.of.issue",
            [("active", "=", True), ("establishment_id", "=", establishment.id)],
            "Select one active Paraguay point of issue.",
        )
        if point.establishment_id != establishment:
            raise ValidationError("SIFEN point of issue does not belong to the establishment.")
        timbrado = self._one("fiscal.py.timbrado", [
            ("active", "=", True), ("tenant_id", "=", tenant.id),
            ("company_id", "=", move.company_id.id), ("environment", "=", environment),
            ("document_type", "=", document_type),
        ], f"Exactly one active Paraguay {document_type} timbrado is required.")
        if timbrado.allowed_point_of_issue_ids and point not in timbrado.allowed_point_of_issue_ids:
            raise ValidationError("The SIFEN point of issue is not allowed by the timbrado.")
        csc = self._one("fiscal.py.csc", [
            ("active", "=", True), ("tenant_id", "=", tenant.id),
            ("company_id", "=", move.company_id.id), ("environment", "=", environment),
        ], "Exactly one active Paraguay CSC configuration is required.")
        sequence = self.env["fiscal.py.sequence"].search([
            ("active", "=", True), ("tenant_id", "=", tenant.id),
            ("company_id", "=", move.company_id.id), ("timbrado_id", "=", timbrado.id),
            ("establishment_id", "=", establishment.id),
            ("point_of_issue_id", "=", point.id), ("document_type", "=", document_type),
        ])
        if len(sequence) != 1:
            raise ValidationError(
                f"Exactly one active Paraguay {document_type} sequence is required."
            )
        return {"tenant": tenant, "adapter": adapter, "issuer": issuer,
                "establishment": establishment, "point": point,
                "timbrado": timbrado, "csc": csc}

    def _receiver_values(self, partner):
        if partner.py_sifen_receiver_profile == "unnamed_consumer":
            return {
                "customer_name": "Sin Nombre", "customer_tax_id": "0",
                "customer_tax_id_type": "unnamed", "customer_email": partner.email or "",
                "py_receiver_nature": "2", "py_receiver_operation_type": "2",
                "py_receiver_id_type": "5", "py_receiver_id_type_description": "Innominado",
                "py_receiver_id_number": "0", "py_receiver_country_code": "PRY",
                "py_receiver_country_description": "Paraguay",
            }
        if partner.py_sifen_receiver_profile != "taxpayer":
            raise ValidationError(
                "Customer SIFEN receiver profile must be configured as B2B taxpayer or unnamed B2C."
            )
        ruc, dv = self._ruc(partner.vat)
        required = (("street", "address"), ("py_sifen_house_number", "house number"),
                    ("py_sifen_department_code", "department code"),
                    ("py_sifen_department_name", "department description"),
                    ("py_sifen_district_code", "district code"),
                    ("py_sifen_district_name", "district description"),
                    ("py_sifen_city_code", "city code"),
                    ("py_sifen_city_name", "city description"),
                    ("py_sifen_taxpayer_type", "taxpayer type"))
        missing = [label for field_name, label in required if not partner[field_name]]
        if not partner.country_id or partner.country_id.code != "PY":
            missing.append("Paraguay country")
        if missing:
            raise ValidationError("Customer SIFEN data is missing: " + ", ".join(missing) + ".")
        return {
            "customer_name": partner.name, "customer_tax_id": f"{ruc}-{dv}",
            "customer_tax_id_type": "ruc", "customer_email": partner.email or "",
            "py_receiver_nature": "1", "py_receiver_taxpayer_type": partner.py_sifen_taxpayer_type,
            "py_receiver_operation_type": "1", "py_receiver_country_code": "PRY",
            "py_receiver_country_description": "Paraguay", "py_receiver_address": partner.street,
            "py_receiver_house_number": partner.py_sifen_house_number,
            "py_receiver_phone": partner.phone or "",
            "py_receiver_department_code": partner.py_sifen_department_code,
            "py_receiver_department_name": partner.py_sifen_department_name,
            "py_receiver_district_code": partner.py_sifen_district_code,
            "py_receiver_district_name": partner.py_sifen_district_name,
            "py_receiver_city_code": partner.py_sifen_city_code,
            "py_receiver_city_name": partner.py_sifen_city_name,
        }

    def _document_values(
        self,
        move,
        config,
        receiver,
        snapshot_at,
        *,
        email_delivery_policy="company_default",
    ):
        issuer = config["issuer"]
        values = dict(receiver, **{
            "issue_datetime": snapshot_at, "py_issuer_id": issuer.id,
            "py_issuer_ruc": issuer.ruc, "py_issuer_ruc_dv": issuer.ruc_dv,
            "py_issuer_taxpayer_type": issuer.taxpayer_type,
            "py_establishment_id": config["establishment"].id,
            "py_point_of_issue_id": config["point"].id,
            "py_timbrado_id": config["timbrado"].id, "py_csc_id": config["csc"].id,
            "py_emission_type": "1",
            "py_transaction_type_code": (
                "10" if move.move_type == "in_invoice" else "2"
            ),
            "py_tax_type_code": (
                "4" if move.move_type == "in_invoice" else "1"
            ),
            "py_currency": move.currency_id.name,
            "py_sale_condition_code": move.py_sale_condition_code,
            "py_payment_type_code": "1" if move.py_sale_condition_code == "1" else False,
            "py_payment_amount": move.amount_total if move.py_sale_condition_code == "1" else 0,
            "py_payment_currency": move.currency_id.name,
            "py_credit_debit_reason_code": move.py_credit_note_reason_code or False,
            "py_email_delivery_policy": email_delivery_policy,
        })
        values.update(self._credit_values(move))
        return values

    def _credit_values(self, move):
        if move.py_sale_condition_code != "2":
            return {
                "py_credit_condition_code": False,
                "py_credit_term": False,
                "py_installment_count": 0,
                "py_installments_json": False,
            }
        term_lines = move.line_ids.filtered(
            lambda line: line.account_id.account_type
            in ("asset_receivable", "liability_payable")
        ).sorted(lambda line: (line.date_maturity or move.invoice_date, line.id))
        if not term_lines:
            raise ValidationError(
                "Credit fiscal documents require posted accounting maturity lines."
            )
        installments = []
        total = Decimal("0")
        for line in term_lines:
            if not line.date_maturity:
                raise ValidationError("Every credit installment requires a maturity date.")
            amount = abs(Decimal(str(
                line.amount_currency
                if line.currency_id == move.currency_id and line.amount_currency
                else line.balance
            )))
            if amount <= 0:
                raise ValidationError("Every credit installment must have a positive amount.")
            installments.append({
                "sequence": len(installments) + 1,
                "currency": move.currency_id.name,
                "amount": format(amount, "f"),
                "due_date": line.date_maturity.isoformat(),
                "source_move_line_id": line.id,
            })
            total += amount
        if not move.currency_id.is_zero(float(total - Decimal(str(move.amount_total)))):
            raise ValidationError(
                "Credit installment amounts must reconcile exactly with the fiscal total."
            )
        return {
            "py_credit_condition_code": "2",
            "py_credit_term": False,
            "py_installment_count": len(installments),
            "py_installments_json": json.dumps(
                installments, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ),
        }

    def _validate_correction_note(self, move, document_type, original, config):
        if document_type not in ("credit_note", "debit_note"):
            return
        self._lock_original_document(original)
        problems = []
        if original.state != "accepted" or not original.authority_receipt_ref:
            problems.append("The original Paraguay invoice must be accepted by SIFEN.")
        if not original.py_cdc or len(original.py_cdc) != 44:
            problems.append("The original Paraguay invoice requires a valid CDC.")
        if original.adapter_config_id != config["adapter"]:
            problems.append("Original invoice and correction note adapter scope do not match.")
        if original.currency_id != move.currency_id:
            problems.append("Correction note currency must match the original invoice.")
        if original.partner_id.commercial_partner_id != move.partner_id.commercial_partner_id:
            problems.append("Correction note customer must match the original invoice customer.")
        if original.py_receiver_nature != "1":
            problems.append(
                "The original invoice receiver must be identified for a Paraguay correction note."
            )
        if not move.py_credit_note_reason_code:
            problems.append(f"Select the SIFEN {document_type.replace('_', ' ')} reason.")
        if document_type == "credit_note":
            existing_amount = sum(
                self.env["fiscal.document"].sudo().search([
                    ("original_document_id", "=", original.id),
                    ("document_type", "=", "credit_note"),
                    ("active", "=", True),
                    ("state", "!=", "cancelled"),
                    ("account_move_id", "!=", move.id),
                ]).mapped("amount_total")
            )
            if Decimal(str(existing_amount)) + Decimal(str(move.amount_total)) > Decimal(
                str(original.amount_total)
            ):
                problems.append(
                    "Credit notes cannot exceed the remaining amount of the original invoice."
                )
        if problems:
            raise ValidationError(" ".join(problems))

    def _lock_original_document(self, original):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "SELECT id FROM fiscal_document WHERE id = %s FOR UPDATE NOWAIT",
                    [original.id],
                )
                locked = self.env.cr.fetchone()
        except errors.LockNotAvailable:
            raise ValidationError(
                "Another correction-note preparation is already evaluating this original invoice."
            ) from None
        if not locked:
            raise ValidationError("The original fiscal document no longer exists.")

    def _line_values(self, line, _neutral):
        if len(line.tax_ids) != 1:
            raise ValidationError(f"Invoice line {line.name!r} requires exactly one explicitly mapped SIFEN tax.")
        tax = line.tax_ids
        mapping = self.TAX_MAPPING.get(tax.py_sifen_tax_treatment)
        if not mapping:
            raise ValidationError(f"Invoice line {line.name!r} has no explicit SIFEN tax mapping.")
        rate = mapping["rate"]
        if tax.amount_type != "percent" or abs(tax.amount - rate) > 0.000001:
            raise ValidationError(f"Invoice line {line.name!r} has an inconsistent SIFEN tax rate.")
        if not tax.price_include:
            raise ValidationError(f"Invoice line {line.name!r} uses unsupported tax-exclusive pricing.")
        is_self_invoice = line.move_id.move_type == "in_invoice"
        if is_self_invoice and (mapping["affectation"] != "3" or tax.amount):
            raise ValidationError(
                f"Self-invoice line {line.name!r} must not include VAT; "
                "use the explicit zero-rate SIFEN mapping."
            )
        discount = Decimal(str(line.price_unit)) * Decimal(str(line.discount)) / Decimal("100")
        if is_self_invoice:
            return {
                "py_internal_code": line.product_id.default_code or str(line.id),
                "py_unit_measure_code": "77", "py_unit_measure_description": "UNI",
                "py_tax_affectation": False, "py_tax_rate": 0.0,
                "py_tax_proportion": 0.0, "py_tax_base": 0.0,
                "py_tax_amount": 0.0, "py_exempt_base": 0.0,
                "py_discount_amount": float(discount), "tax_category_code": False,
                "tax_rate": 0.0, "tax_base_amount": 0.0, "fiscal_unit_code": "77",
            }
        return {
            "py_internal_code": line.product_id.default_code or str(line.id),
            "py_unit_measure_code": "77", "py_unit_measure_description": "UNI",
            "py_tax_affectation": mapping["affectation"], "py_tax_rate": rate,
            "py_tax_proportion": 100.0 if rate else 0.0,
            "py_tax_base": line.price_subtotal if rate else 0.0,
            "py_tax_amount": line.price_total - line.price_subtotal,
            "py_exempt_base": line.price_total if not rate else 0.0,
            "py_discount_amount": float(discount), "tax_category_code": mapping["affectation"],
            "tax_rate": rate, "tax_base_amount": line.price_subtotal if rate else 0.0,
            "fiscal_unit_code": "77",
        }

    def _one(self, model, domain, message):
        records = self.env[model].search(domain)
        if len(records) != 1:
            raise ValidationError(message)
        return records

    def _ruc(self, value):
        parts = str(value or "").strip().split("-")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit() or len(parts[1]) != 1:
            raise ValidationError("Customer RUC must use the numeric base-DV format.")
        return parts
