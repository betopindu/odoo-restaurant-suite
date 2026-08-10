import hashlib
import re
from dataclasses import dataclass, field

from odoo.exceptions import AccessError, ValidationError

from odoo.addons.einvoice_py.services.py_kude_service import PyKudeService


@dataclass(frozen=True, slots=True, repr=False)
class PyKudePreviewResult:
    pdf_bytes: bytes = field(repr=False)
    filename: str
    sha256: str
    page_count: int
    cdc: str
    logo_rendered: bool

    def __repr__(self):
        return (
            "PyKudePreviewResult("
            f"filename={self.filename!r}, sha256={self.sha256!r}, "
            f"page_count={self.page_count!r}, cdc={self.cdc!r}, "
            f"logo_rendered={self.logo_rendered!r}, "
            "pdf_bytes=<redacted>)"
        )


class PyKudePreviewService:
    """Render a non-authoritative Paraguay preview without fiscal persistence."""

    BLOCKED_STATES = frozenset({"validation_error", "cancelled"})
    DOCUMENT_PREFIXES = {
        "invoice": "FE",
    }

    def __init__(self, env, *, kude_service=None):
        self.env = env
        self.kude_service = kude_service or PyKudeService(env)

    def render(self, *, document):
        document.ensure_one()
        self._check_access(document)
        self._validate_document(document)
        _attachment, payload = self.kude_service.load_payload(document)
        self.kude_service.validate_payload(payload, document)
        logo_bytes = self.kude_service.load_company_logo(document)
        pdf_bytes, page_count = self.kude_service.render_pdf(
            payload,
            preview=True,
            logo_bytes=logo_bytes,
        )
        return PyKudePreviewResult(
            pdf_bytes=pdf_bytes,
            filename=self._filename(document),
            sha256=hashlib.sha256(pdf_bytes).hexdigest(),
            page_count=page_count,
            cdc=payload["cdc"],
            logo_rendered=bool(logo_bytes),
        )

    def _check_access(self, document):
        document.check_access_rights("read")
        document.check_access_rule("read")
        if document.company_id not in self.env.companies:
            raise AccessError(
                "Fiscal document company is not available to the current user."
            )

    def _validate_document(self, document):
        if (document.country_code or "").upper() != "PY":
            raise ValidationError("KuDE preview requires a Paraguay document.")
        if document.document_type != "invoice":
            raise ValidationError(
                "KuDE preview currently supports Paraguay invoices only."
            )
        if document.state in self.BLOCKED_STATES:
            raise ValidationError(
                "KuDE preview requires a complete, non-cancelled fiscal document."
            )

    def _filename(self, document):
        number = (document.py_full_number or document.fiscal_number or "").strip()
        if not number or not re.fullmatch(r"[0-9-]+", number):
            raise ValidationError("KuDE preview requires a safe document number.")
        prefix = self.DOCUMENT_PREFIXES[document.document_type]
        return f"PREVIEW-{prefix}-{number}.pdf"
