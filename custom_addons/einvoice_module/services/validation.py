class FiscalValidationResult:
    def __init__(self, errors=None):
        self.errors = errors or []

    @property
    def is_valid(self):
        return not self.errors

    def summary(self):
        return "; ".join(self.errors)


class FiscalDocumentValidationService:
    def validate(self, document):
        errors = []

        if not document.tenant_id:
            errors.append("Tenant is required.")
        if not document.company_id:
            errors.append("Company is required.")
        if not document.document_type:
            errors.append("Document type is required.")
        if not document.country_code:
            errors.append("Country code is required.")
        if not document.environment:
            errors.append("Environment is required.")
        if not document.adapter_code and not document.adapter_config_id:
            errors.append("Adapter code or adapter config is required.")
        if not document.customer_name and not document.partner_id:
            errors.append("Customer name or partner is required.")
        if document.amount_total <= 0:
            errors.append("Amount total must be greater than zero.")
        if not document.line_ids:
            errors.append("At least one document line is required.")

        for line in document.line_ids:
            line_label = line.product_name or line.product_id.display_name or f"Line {line.id}"
            if not line.product_name and not line.product_id:
                errors.append(f"{line_label}: product name or product is required.")
            if line.quantity <= 0:
                errors.append(f"{line_label}: quantity must be greater than zero.")
            if line.price_unit < 0:
                errors.append(f"{line_label}: price unit cannot be negative.")
            if line.total < 0:
                errors.append(f"{line_label}: total cannot be negative.")

        return FiscalValidationResult(errors)
