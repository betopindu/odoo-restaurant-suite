import json

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_authority_incident_service import (
    PySifenAuthorityIncidentService,
)
from odoo.addons.einvoice_py.services.py_sifen_retry_signing_time_service import (
    PySifenRetrySigningTimeService,
)
from odoo.addons.einvoice_py.services.py_source_artifact_service import (
    PySourceArtifactService,
)
from odoo.addons.einvoice_py.services.py_sifen_transmission_persistence_service import (
    PySifenTransmissionPersistenceService,
)


class PySifenManualRetryService:
    """Guard and execute an explicitly authorized SIFEN manual retry."""

    def __init__(
        self,
        env,
        *,
        persistence_service=None,
        incident_service=None,
        signing_time_service=None,
        source_artifact_service=None,
    ):
        self.env = env
        self.persistence_service = persistence_service or PySifenTransmissionPersistenceService(env)
        self.incident_service = incident_service or PySifenAuthorityIncidentService()
        self.signing_time_service = signing_time_service or PySifenRetrySigningTimeService(env)
        self.source_artifact_service = source_artifact_service or PySourceArtifactService(env)

    def retry(self, *, document, payload=None, signing_timestamp=None):
        fresh_timestamp = self.signing_time_service.fresh(
            document=document,
            reference_instant=signing_timestamp,
        )
        self.validate(
            document=document,
            signing_timestamp=fresh_timestamp,
        )
        if payload is not None:
            self.source_artifact_service.persist_payload(
                document=document, payload=payload
            )
        _current_attachment, current_payload = (
            self.source_artifact_service.read_current_payload(document=document)
        )
        return self.persistence_service.submit_and_persist(
            document=document,
            payload=current_payload,
            signing_timestamp=fresh_timestamp,
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
        self.signing_time_service.fresh(
            document=document,
            reference_instant=signing_timestamp,
        )
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
