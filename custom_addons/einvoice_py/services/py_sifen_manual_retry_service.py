import json

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_authority_incident_service import (
    PySifenAuthorityIncidentService,
)
from odoo.addons.einvoice_py.services.py_sifen_datetime_service import (
    PySifenDatetimeService,
)
from odoo.addons.einvoice_py.services.py_sifen_transmission_persistence_service import (
    PySifenTransmissionPersistenceService,
)
from odoo.addons.einvoice_py.services.py_signed_xml_attachment_service import (
    PySignedXmlAttachmentService,
)


class PySifenManualRetryService:
    """Guard and execute an explicitly authorized SIFEN manual retry."""

    def __init__(self, env, *, persistence_service=None, incident_service=None):
        self.env = env
        self.persistence_service = persistence_service or PySifenTransmissionPersistenceService(env)
        self.incident_service = incident_service or PySifenAuthorityIncidentService()

    def retry(self, *, document, payload, signing_timestamp):
        self.validate(
            document=document,
            signing_timestamp=signing_timestamp,
        )
        return self.persistence_service.submit_and_persist(
            document=document,
            payload=payload,
            signing_timestamp=signing_timestamp,
        )

    def validate(self, *, document, signing_timestamp):
        document.ensure_one()
        cdc = (document.country_identifier or document.py_cdc or "").strip()
        if not cdc:
            raise ValidationError("SIFEN manual retry requires the current document CDC.")
        domain = self._scope(document, cdc)
        transmissions = self.env["fiscal.transmission"].sudo().search(
            domain, order="attempt_number desc,id desc"
        )
        if document.state == "accepted" or transmissions.filtered(lambda tx: tx.state == "accepted"):
            raise ValidationError("An accepted SIFEN document cannot be retried.")
        if transmissions.filtered(self._is_ambiguous):
            raise ValidationError("An ambiguous SIFEN submission requires reconciliation before retry.")
        previous = transmissions[:1]
        if not previous or previous.state != "rejected":
            raise ValidationError("SIFEN manual retry requires an explicit authority rejection.")
        classification = self.incident_service.classify(
            authority_code=previous.authority_status_code,
            authority_message=previous.authority_message,
        )
        if not classification.manual_retry_allowed:
            raise ValidationError("The SIFEN authority result is not eligible for manual retry.")
        self._validate_fresh_signature(document, signing_timestamp)
        return classification

    def _scope(self, document, cdc):
        return [
            ("transmission_type", "=", "submit"),
            ("country_code", "=", "PY"),
            ("environment", "=", document.environment),
            ("tenant_id", "=", document.tenant_id.id),
            ("company_id", "=", document.company_id.id),
            ("country_identifier", "=", cdc),
        ]

    def _is_ambiguous(self, transmission):
        if transmission.state == "manual_review" or transmission.error_code == "ambiguous_submission":
            return True
        try:
            metadata = json.loads(transmission.metadata_json or "{}")
        except (TypeError, ValueError):
            return False
        return bool(metadata.get("ambiguous"))

    def _validate_fresh_signature(self, document, signing_timestamp):
        current = PySignedXmlAttachmentService(self.env).current(document=document)
        if not current:
            return
        try:
            metadata = json.loads(current.metadata_json or "{}")
        except (TypeError, ValueError):
            metadata = {}
        previous = str(metadata.get("signing_time") or "")
        candidate = PySifenDatetimeService.format_signing_datetime(signing_timestamp)
        if previous and candidate <= previous:
            raise ValidationError(
                "SIFEN manual retry requires a fresh signing timestamp and signed artifact."
            )
