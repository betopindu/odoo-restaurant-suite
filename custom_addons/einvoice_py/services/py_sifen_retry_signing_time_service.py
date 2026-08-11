from odoo import fields
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_datetime_service import (
    PySifenDatetimeService,
)
from odoo.addons.einvoice_py.services.py_signed_xml_attachment_service import (
    PySignedXmlAttachmentService,
)


class PySifenRetrySigningTimeService:
    """Provide a fresh, testable signing reference instant for every retry."""

    def __init__(self, env, *, now_provider=None):
        self.env = env
        self.now_provider = now_provider or fields.Datetime.now

    def fresh(self, *, document, reference_instant=None):
        reference = reference_instant if reference_instant is not None else self.now_provider()
        if isinstance(reference, str) and PySifenDatetimeService._is_serialized_fiscal_time(reference):
            raise ValidationError(
                "SIFEN retry signing reference must be a fresh instant."
            )
        candidate = PySifenDatetimeService.format_signing_datetime(reference)
        current = PySignedXmlAttachmentService(self.env).current(document=document)
        if current:
            metadata = PySignedXmlAttachmentService(self.env)._metadata(current)
            previous = str(metadata.get("signing_time") or "")
            if previous and not PySifenDatetimeService._is_serialized_fiscal_time(previous):
                raise ValidationError(
                    "Stored Paraguay retry signing metadata is invalid."
                )
            if previous and candidate <= previous:
                raise ValidationError(
                    "SIFEN retry requires a fresh signing timestamp and signed artifact."
                )
        return reference
