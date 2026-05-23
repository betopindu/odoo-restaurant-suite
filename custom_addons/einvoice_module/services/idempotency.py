from odoo.exceptions import ValidationError


class FiscalIdempotencyService:
    def __init__(self, env):
        self.env = env

    def build_key_from_source(
        self,
        source_system,
        source_model=None,
        source_res_id=None,
        source_external_id=None,
        document_type=None,
    ):
        parts = [
            source_system or "",
            source_model or "",
            str(source_res_id or ""),
            source_external_id or "",
            document_type or "",
        ]
        return "|".join(parts)

    def find_existing_document(self, tenant_id, document_type, idempotency_key, exclude_ids=None):
        if not tenant_id or not document_type or not idempotency_key:
            return self.env["fiscal.document"].browse()

        domain = [
            ("active", "=", True),
            ("tenant_id", "=", tenant_id),
            ("document_type", "=", document_type),
            ("idempotency_key", "=", idempotency_key),
        ]
        if exclude_ids:
            domain.append(("id", "not in", list(exclude_ids)))
        return self.env["fiscal.document"].sudo().search(domain, limit=1)

    def ensure_unique(self, entries):
        seen = set()
        for entry in entries:
            if not entry.get("active", True) or not entry.get("idempotency_key"):
                continue

            key = (
                entry.get("tenant_id"),
                entry.get("document_type") or "invoice",
                entry.get("idempotency_key"),
            )
            if key in seen:
                raise ValidationError(
                    "Duplicate fiscal document idempotency key in the same operation."
                )
            seen.add(key)

            existing = self.find_existing_document(
                key[0],
                key[1],
                key[2],
                exclude_ids=entry.get("exclude_ids"),
            )
            if existing:
                raise ValidationError(
                    "An active fiscal document already exists for this tenant, "
                    "document type, and idempotency key."
                )
