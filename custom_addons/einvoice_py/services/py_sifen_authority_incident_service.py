import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class PySifenAuthorityIncidentClassification:
    incident_type: str = ""
    manual_retry_allowed: bool = False
    automatic_retry_allowed: bool = False


class PySifenAuthorityIncidentService:
    """Classify exceptional authority incidents separately from fiscal results."""

    PKI_MESSAGE = "error inesperado pki"

    def classify(self, *, authority_code, authority_message):
        if (
            str(authority_code or "").strip() == "0100"
            and self._normalize(authority_message) == self.PKI_MESSAGE
        ):
            return PySifenAuthorityIncidentClassification(
                incident_type="transient_authority_incident",
                manual_retry_allowed=True,
                automatic_retry_allowed=False,
            )
        return PySifenAuthorityIncidentClassification()

    def _normalize(self, value):
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        ascii_text = "".join(
            character for character in normalized
            if not unicodedata.combining(character)
        ).lower()
        return " ".join(re.findall(r"[a-z0-9]+", ascii_text))
