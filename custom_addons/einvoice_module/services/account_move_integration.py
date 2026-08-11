import hashlib
import json

from psycopg2 import errors

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_module.services.idempotency import FiscalIdempotencyService


class FiscalDocumentFromAccountMoveService:
    """Create a country-neutral immutable fiscal snapshot from a posted invoice."""

    SOURCE_SYSTEM = "odoo"
    SOURCE_MODEL = "account.move"

    def __init__(self, env):
        self.env = env

    def create(
        self,
        *,
        move,
        tenant,
        adapter_config,
        document_values=None,
        line_value_provider=None,
    ):
        move.ensure_one()
        tenant.ensure_one()
        adapter_config.ensure_one()
        self._validate(move, tenant, adapter_config)
        self._lock(move)
        existing = self._existing(move, adapter_config)
        if existing:
            return existing

        invoice_lines = move.invoice_line_ids.sorted(lambda line: (line.sequence, line.id))
        line_values = [
            self._line_values(line, line_value_provider)
            for line in invoice_lines
        ]
        snapshot = self._snapshot(move, tenant, adapter_config, line_values)
        values = {
            "name": move.name,
            "tenant_id": tenant.id,
            "company_id": move.company_id.id,
            "currency_id": move.currency_id.id,
            "adapter_config_id": adapter_config.id,
            "document_type": "invoice",
            "state": "draft",
            "country_code": adapter_config.country_code.upper(),
            "environment": adapter_config.environment,
            "adapter_code": adapter_config.adapter_code,
            "source_system": self.SOURCE_SYSTEM,
            "source_model": self.SOURCE_MODEL,
            "source_res_id": move.id,
            "source_external_id": str(move.id),
            "source_reference": move.name,
            "account_move_id": move.id,
            "idempotency_key": FiscalIdempotencyService(self.env).build_key_from_source(
                self.SOURCE_SYSTEM,
                self.SOURCE_MODEL,
                move.id,
                source_external_id=str(adapter_config.id),
                document_type="invoice",
            ),
            "partner_id": move.partner_id.id,
            "customer_name": move.partner_id.commercial_partner_id.name,
            "customer_tax_id": move.partner_id.commercial_partner_id.vat or "",
            "customer_tax_id_type": "tax_id",
            "customer_email": move.partner_id.email or "",
            "issue_datetime": snapshot["snapshot_at"],
            "amount_untaxed": move.amount_untaxed,
            "amount_tax": move.amount_tax,
            "amount_discount": sum(
                line.price_unit * line.quantity * line.discount / 100
                for line in invoice_lines
            ),
            "amount_total": move.amount_total,
            "metadata_json": self._json(snapshot),
            "line_ids": [(0, 0, values) for values in line_values],
        }
        values.update(document_values or {})
        try:
            with self.env.cr.savepoint():
                return self.env["fiscal.document"].create(values)
        except errors.UniqueViolation:
            existing = self._existing(move, adapter_config)
            if existing:
                return existing
            raise

    def _validate(self, move, tenant, adapter):
        problems = []
        if move.move_type != "out_invoice":
            problems.append("Only customer invoices can create fiscal documents.")
        if move.state != "posted":
            problems.append("The customer invoice must be posted first.")
        if move.company_id != tenant.company_id:
            problems.append("Fiscal tenant and invoice company do not match.")
        if move.company_id != adapter.company_id or tenant != adapter.tenant_id:
            problems.append("Fiscal adapter scope does not match the invoice.")
        if not adapter.active:
            problems.append("The fiscal adapter is inactive.")
        if move.amount_total <= 0 or not move.invoice_line_ids:
            problems.append("The customer invoice must contain a positive fiscal amount.")
        if not move.partner_id:
            problems.append("The customer invoice requires a customer.")
        if not move.currency_id:
            problems.append("The customer invoice requires a currency.")
        if problems:
            raise ValidationError(" ".join(problems))

    def _lock(self, move):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "SELECT id FROM account_move WHERE id = %s FOR UPDATE NOWAIT",
                    [move.id],
                )
                locked = self.env.cr.fetchone()
        except errors.LockNotAvailable:
            raise ValidationError(
                "Fiscal document creation is already in progress for this invoice."
            ) from None
        if not locked:
            raise ValidationError("The source invoice no longer exists.")

    def _existing(self, move, adapter):
        existing = self.env["fiscal.document"].sudo().search([
            ("account_move_id", "=", move.id),
            ("adapter_config_id", "=", adapter.id),
            ("active", "=", True),
        ], limit=1)
        if not existing:
            return existing
        existing = existing.with_env(self.env)
        existing.check_access_rights("read")
        existing.check_access_rule("read")
        return existing

    def _line_values(self, line, provider):
        values = {
            "sequence": line.sequence,
            "source_line_id": line.id,
            "source_external_line_id": str(line.id),
            "product_id": line.product_id.id,
            "product_code": line.product_id.default_code or "",
            "product_name": line.product_id.display_name or line.name,
            "description": line.name,
            "quantity": line.quantity,
            "uom_id": line.product_uom_id.id,
            "price_unit": line.price_unit,
            "discount": line.discount,
            "subtotal": line.price_subtotal,
            "tax_amount": line.price_total - line.price_subtotal,
            "total": line.price_total,
            "tax_ids": [(6, 0, line.tax_ids.ids)],
            "metadata_json": self._json({
                "schema_version": 1,
                "source_model": "account.move.line",
                "source_line_id": line.id,
                "source_price_unit": str(line.price_unit),
                "source_discount_percent": str(line.discount),
                "tax_ids": line.tax_ids.ids,
            }),
        }
        if provider:
            values.update(provider(line, values.copy()) or {})
        return values

    def _snapshot(self, move, tenant, adapter, line_values):
        partner = move.partner_id.commercial_partner_id
        snapshot_at = self.env.context.get("fiscal_snapshot_at") or move.write_date
        data = {
            "schema_version": 1,
            "snapshot_at": snapshot_at,
            "source": {
                "system": self.SOURCE_SYSTEM,
                "model": self.SOURCE_MODEL,
                "record_id": move.id,
                "reference": move.name,
                "write_date": move.write_date,
            },
            "scope": {
                "tenant_id": tenant.id,
                "company_id": move.company_id.id,
                "adapter_config_id": adapter.id,
                "country_code": adapter.country_code.upper(),
                "environment": adapter.environment,
            },
            "invoice": {
                "invoice_date": move.invoice_date,
                "currency": move.currency_id.name,
                "payment_term_id": move.invoice_payment_term_id.id,
                "move_type": move.move_type,
            },
            "customer": {
                "partner_id": partner.id,
                "name": partner.name,
                "tax_id": partner.vat or "",
                "country_code": partner.country_id.code or "",
                "street": partner.street or "",
                "street2": partner.street2 or "",
                "city": partner.city or "",
                "state": partner.state_id.name or "",
                "zip": partner.zip or "",
                "phone": partner.phone or "",
                "email": partner.email or "",
            },
            "totals": {
                "untaxed": str(move.amount_untaxed),
                "tax": str(move.amount_tax),
                "total": str(move.amount_total),
                "currency": move.currency_id.name,
            },
            "line_source_ids": [values["source_line_id"] for values in line_values],
        }
        canonical = self._json(data).encode("utf-8")
        data["snapshot_sha256"] = hashlib.sha256(canonical).hexdigest()
        return data

    def _json(self, value):
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True, default=str)
