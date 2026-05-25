from gevent import Timeout

from odoo.addons.einvoice_module.services.idempotency import FiscalIdempotencyService
from odoo.addons.einvoice_module.services.orchestrator import FiscalOrchestrator


class FiscalApiPayloadError(Exception):
    def __init__(self, details):
        super().__init__("Invalid fiscal document payload.")
        self.details = details


class FiscalApiDocumentMapper:
    SYNC_TIMEOUT_SECONDS = 5
    ALLOWED_FIELDS = {
        "idempotency_key",
        "processing_mode",
        "document_type",
        "country_code",
        "environment",
        "adapter_code",
        "source",
        "customer",
        "currency",
        "amounts",
        "lines",
    }
    SOURCE_FIELDS = {"system", "external_id", "reference"}
    CUSTOMER_FIELDS = {"name", "tax_id", "tax_id_type", "email"}
    AMOUNT_FIELDS = {"untaxed", "tax", "discount", "total"}
    LINE_FIELDS = {
        "product_code",
        "product_name",
        "quantity",
        "price_unit",
        "subtotal",
        "tax_amount",
        "total",
    }
    DOCUMENT_TYPES = {"invoice", "credit_note", "debit_note", "receipt"}
    ENVIRONMENTS = {"test", "production"}

    def __init__(self, env, api_key):
        self.env = env
        self.api_key = api_key

    def create_or_get_document(self, payload):
        details = self._validate_payload(payload)
        if details:
            raise FiscalApiPayloadError(details)

        document_type = payload["document_type"]
        idempotency_key = payload["idempotency_key"].strip()
        idempotency = FiscalIdempotencyService(self.env)
        existing = idempotency.find_existing_document(
            self.api_key.tenant_id.id,
            document_type,
            idempotency_key,
        )
        if existing:
            return existing, True

        source = payload.get("source") or {}
        customer = payload["customer"]
        amounts = payload["amounts"]
        currency = self._get_currency(payload.get("currency"))
        vals = {
            "name": (
                source.get("reference")
                or source.get("external_id")
                or idempotency_key
            ),
            "tenant_id": self.api_key.tenant_id.id,
            "company_id": self.api_key.company_id.id,
            "currency_id": currency.id,
            "document_type": document_type,
            "country_code": payload["country_code"].upper(),
            "environment": payload["environment"],
            "adapter_code": payload["adapter_code"],
            "source_system": source.get("system"),
            "source_external_id": source.get("external_id"),
            "source_reference": source.get("reference"),
            "idempotency_key": idempotency_key,
            "customer_name": customer["name"],
            "customer_tax_id": customer.get("tax_id"),
            "customer_tax_id_type": customer.get("tax_id_type"),
            "customer_email": customer.get("email"),
            "amount_untaxed": amounts.get("untaxed", 0),
            "amount_tax": amounts.get("tax", 0),
            "amount_discount": amounts.get("discount", 0),
            "amount_total": amounts["total"],
        }
        document_model = (
            self.env["fiscal.document"]
            .sudo()
            .with_company(self.api_key.company_id)
            .with_context(einvoice_creation_actor_context={"actor_type": "api"})
        )
        document = document_model.create(vals)
        line_model = self.env["fiscal.document.line"].sudo()
        line_model.create([
            {
                "document_id": document.id,
                "sequence": index * 10,
                "product_code": line.get("product_code"),
                "product_name": line["product_name"],
                "quantity": line["quantity"],
                "price_unit": line["price_unit"],
                "subtotal": line.get("subtotal", 0),
                "tax_amount": line.get("tax_amount", 0),
                "total": line["total"],
            }
            for index, line in enumerate(payload["lines"], start=1)
        ])
        self.env["fiscal.attachment"].sudo().create_json_payload_attachment(
            document,
            "canonical_json",
            f"{document.uuid}-canonical-request.json",
            payload,
        )

        orchestrator = FiscalOrchestrator(document.env)
        actor_context = {"actor_type": "api"}
        orchestrator.mark_ready(document, actor_context=actor_context)
        orchestrator.queue(document, actor_context=actor_context)
        return document, False

    def process_immediately(self, document):
        if document.state != "queued":
            return document
        try:
            with self.env.cr.savepoint():
                with Timeout(self.SYNC_TIMEOUT_SECONDS):
                    FiscalOrchestrator(document.env).process_document(
                        document,
                        actor_context={"actor_type": "api"},
                    )
        except Timeout:
            # Leave the previously queued document available for cron processing.
            document.invalidate_recordset()
        return document

    def _get_currency(self, currency_code):
        if not currency_code:
            return self.api_key.company_id.currency_id
        currency = self.env["res.currency"].sudo().search(
            [("name", "=", currency_code.upper())],
            limit=1,
        )
        if not currency:
            raise FiscalApiPayloadError([
                f"currency '{currency_code}' is not configured.",
            ])
        return currency

    def _validate_payload(self, payload):
        details = []
        unexpected_fields = set(payload) - self.ALLOWED_FIELDS
        if unexpected_fields:
            details.append(
                "Unsupported fields: " + ", ".join(sorted(unexpected_fields)) + "."
            )

        self._require_text(payload, "idempotency_key", details)
        document_type = payload.get("document_type")
        if document_type not in self.DOCUMENT_TYPES:
            details.append("document_type must be a supported fiscal document type.")
        self._require_text(payload, "country_code", details)
        if isinstance(payload.get("country_code"), str) and len(payload["country_code"]) != 2:
            details.append("country_code must contain exactly two characters.")
        if payload.get("environment") not in self.ENVIRONMENTS:
            details.append("environment must be test or production.")
        self._require_text(payload, "adapter_code", details)
        if payload.get("currency") is not None and not self._is_nonempty_text(payload["currency"]):
            details.append("currency must be a non-empty string when provided.")

        source = payload.get("source")
        if source is not None:
            self._validate_object(source, "source", self.SOURCE_FIELDS, details)

        customer = payload.get("customer")
        if not isinstance(customer, dict):
            details.append("customer must be an object.")
        else:
            self._validate_object(customer, "customer", self.CUSTOMER_FIELDS, details)
            self._require_text(customer, "name", details, prefix="customer.")

        amounts = payload.get("amounts")
        if not isinstance(amounts, dict):
            details.append("amounts must be an object.")
        else:
            self._validate_object(amounts, "amounts", self.AMOUNT_FIELDS, details)
            self._require_number(amounts, "total", details, minimum=0.0000001, prefix="amounts.")
            for field_name in ("untaxed", "tax", "discount"):
                if field_name in amounts:
                    self._require_number(amounts, field_name, details, prefix="amounts.")

        lines = payload.get("lines")
        if not isinstance(lines, list) or not lines:
            details.append("lines must be a non-empty array.")
        else:
            for index, line in enumerate(lines):
                prefix = f"lines[{index}]."
                if not isinstance(line, dict):
                    details.append(f"lines[{index}] must be an object.")
                    continue
                self._validate_object(line, f"lines[{index}]", self.LINE_FIELDS, details)
                self._require_text(line, "product_name", details, prefix=prefix)
                self._require_number(line, "quantity", details, minimum=0.0000001, prefix=prefix)
                self._require_number(line, "price_unit", details, minimum=0, prefix=prefix)
                self._require_number(line, "total", details, minimum=0, prefix=prefix)
                for field_name in ("subtotal", "tax_amount"):
                    if field_name in line:
                        self._require_number(line, field_name, details, minimum=0, prefix=prefix)
        return details

    def _validate_object(self, value, label, allowed_fields, details):
        if not isinstance(value, dict):
            details.append(f"{label} must be an object.")
            return
        unexpected_fields = set(value) - allowed_fields
        if unexpected_fields:
            details.append(
                f"Unsupported {label} fields: "
                + ", ".join(sorted(unexpected_fields))
                + "."
            )

    def _require_text(self, values, field_name, details, prefix=""):
        if not self._is_nonempty_text(values.get(field_name)):
            details.append(f"{prefix}{field_name} is required.")

    def _require_number(self, values, field_name, details, minimum=None, prefix=""):
        value = values.get(field_name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            details.append(f"{prefix}{field_name} must be a number.")
            return
        if minimum is not None and value < minimum:
            details.append(f"{prefix}{field_name} must be at least {minimum}.")

    def _is_nonempty_text(self, value):
        return isinstance(value, str) and bool(value.strip())
