from decimal import Decimal

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

    def create(self, *, move):
        move.ensure_one()
        config = self._configuration(move)
        if move.currency_id.name != "PYG":
            raise ValidationError("Paraguay invoice preparation currently supports PYG only.")
        receiver = self._receiver_values(move.partner_id.commercial_partner_id)
        snapshot_at = self.snapshot_time_provider()
        document = FiscalDocumentFromAccountMoveService(
            move.with_context(fiscal_snapshot_at=snapshot_at).env
        ).create(
            move=move,
            tenant=config["tenant"],
            adapter_config=config["adapter"],
            document_values=self._document_values(move, config, receiver, snapshot_at),
            line_value_provider=self._line_values,
        )
        PyNumberingService(self.env).assign_number(document)
        PyCdcService(self.env).generate(document)
        payload = PyPayloadBuilder(self.env).build(document)
        PySourceArtifactService(self.env).persist_payload(document=document, payload=payload)
        if document.state == "draft":
            document.write({"state": "ready", "fiscal_number": document.py_full_number})
        return document

    def _configuration(self, move):
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
            ("document_type", "=", "invoice"),
        ], "Exactly one active Paraguay invoice timbrado is required.")
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
            ("point_of_issue_id", "=", point.id), ("document_type", "=", "invoice"),
        ])
        if len(sequence) != 1:
            raise ValidationError("Exactly one active Paraguay invoice sequence is required.")
        return {"tenant": tenant, "adapter": adapter, "issuer": issuer,
                "establishment": establishment, "point": point,
                "timbrado": timbrado, "csc": csc}

    def _receiver_values(self, partner):
        if partner.py_sifen_receiver_profile == "unnamed_consumer":
            return {
                "customer_name": "INNOMINADO", "customer_tax_id": "0",
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

    def _document_values(self, move, config, receiver, snapshot_at):
        issuer = config["issuer"]
        return dict(receiver, **{
            "issue_datetime": snapshot_at, "py_issuer_id": issuer.id,
            "py_issuer_ruc": issuer.ruc, "py_issuer_ruc_dv": issuer.ruc_dv,
            "py_issuer_taxpayer_type": issuer.taxpayer_type,
            "py_establishment_id": config["establishment"].id,
            "py_point_of_issue_id": config["point"].id,
            "py_timbrado_id": config["timbrado"].id, "py_csc_id": config["csc"].id,
            "py_emission_type": "1", "py_transaction_type_code": "2",
            "py_tax_type_code": "1", "py_currency": move.currency_id.name,
            "py_sale_condition_code": move.py_sale_condition_code,
            "py_payment_type_code": "1" if move.py_sale_condition_code == "1" else False,
            "py_payment_amount": move.amount_total if move.py_sale_condition_code == "1" else 0,
            "py_payment_currency": move.currency_id.name,
        })

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
        discount = Decimal(str(line.price_unit)) * Decimal(str(line.discount)) / Decimal("100")
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
