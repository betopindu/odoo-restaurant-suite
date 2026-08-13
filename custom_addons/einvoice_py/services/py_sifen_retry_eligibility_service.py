import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PySifenRetryEligibility:
    """Immutable, revalidated evidence authorizing one manual retry."""

    evidence_type: str = ""
    manual_retry_allowed: bool = False
    automatic_retry_allowed: bool = False
    document_id: int = 0
    ambiguous_submission_id: int = 0
    reconciliation_query_id: int = 0
    cdc: str = ""
    reason: str = ""


class PySifenRetryEligibilityService:
    """Classify the narrow 0420 recovery path without rewriting history."""

    EVIDENCE_TYPE = "reconciled_not_found_manual_retry_allowed"
    HASH_RE = re.compile(r"[0-9a-f]{64}")

    def __init__(self, env):
        self.env = env

    def classify(self, *, document):
        document.ensure_one()
        cdc = (document.country_identifier or document.py_cdc or "").strip()
        base = {
            "document_id": document.id,
            "cdc": cdc,
        }
        if (
            (document.country_code or "").upper() != "PY"
            or document.environment != "test"
            or not re.fullmatch(r"\d{44}", cdc)
        ):
            return self._blocked(base, "document_scope_invalid")

        transmissions = self.env["fiscal.transmission"].sudo()
        scope = [
            ("document_id", "=", document.id),
            ("tenant_id", "=", document.tenant_id.id),
            ("company_id", "=", document.company_id.id),
            ("country_code", "=", "PY"),
            ("environment", "=", "test"),
            ("country_identifier", "=", cdc),
        ]
        submits = transmissions.search(
            scope + [("transmission_type", "=", "submit")],
            order="id asc",
        )
        queries = transmissions.search(
            scope + [("transmission_type", "=", "status_query")],
            order="id asc",
        )
        if not submits:
            return self._blocked(base, "submission_missing")
        if document.state == "accepted" or transmissions.search_count([
            ("document_id", "=", document.id),
            ("transmission_type", "=", "submit"),
            ("state", "=", "accepted"),
        ]):
            return self._blocked(base, "acceptance_exists")
        if not queries:
            return self._blocked(base, "reconciliation_missing")

        query = queries[-1]
        query_metadata = self._metadata(query)
        normalized = query_metadata.get("normalized_response")
        normalized = normalized if isinstance(normalized, dict) else {}
        linked_ids = query_metadata.get("original_submission_ids")
        if not isinstance(linked_ids, list) or not all(
            isinstance(item, int) for item in linked_ids
        ):
            return self._blocked(base, "reconciliation_link_invalid")
        linked = submits.filtered(lambda item: item.id in linked_ids)
        if not linked:
            return self._blocked(base, "ambiguous_submission_not_linked")
        submission = linked[-1]
        submission_metadata = self._metadata(submission)

        if not self._ambiguous_submission_valid(submission, submission_metadata):
            return self._blocked(base, "ambiguous_submission_invalid")
        if query.id <= submission.id or (
            query.started_at
            and submission.started_at
            and query.started_at < submission.started_at
        ):
            return self._blocked(base, "reconciliation_not_later")
        if transmissions.search_count([
            ("document_id", "=", document.id),
            ("transmission_type", "=", "submit"),
            ("id", ">", submission.id),
        ]):
            return self._blocked(base, "newer_submission_exists")
        if transmissions.search_count([
            ("document_id", "=", document.id),
            ("transmission_type", "=", "status_query"),
            ("id", ">", query.id),
        ]):
            return self._blocked(base, "newer_reconciliation_exists")
        if not self._query_valid(query, query_metadata, normalized):
            return self._blocked(base, "reconciliation_evidence_invalid")

        return PySifenRetryEligibility(
            evidence_type=self.EVIDENCE_TYPE,
            manual_retry_allowed=True,
            automatic_retry_allowed=False,
            document_id=document.id,
            ambiguous_submission_id=submission.id,
            reconciliation_query_id=query.id,
            cdc=cdc,
        )

    def validate_authorization(self, *, document, authorization):
        current = self.classify(document=document)
        return (
            isinstance(authorization, PySifenRetryEligibility)
            and current.manual_retry_allowed
            and authorization == current
        )

    def _ambiguous_submission_valid(self, transmission, metadata):
        return bool(
            transmission.state in ("sent", "manual_review")
            and transmission.error_code == "ambiguous_submission"
            and metadata.get("ambiguous") is True
            and metadata.get("post_started") is True
            and self.HASH_RE.fullmatch(transmission.request_hash or "")
            and not transmission.response_hash
            and not transmission.authority_status_code
        )

    def _query_valid(self, query, metadata, normalized):
        return bool(
            query.state == "manual_review"
            and query.error_code == "reconciliation_not_found"
            and 200 <= (query.http_status or 0) < 300
            and query.authority_status_code == "0420"
            and self.HASH_RE.fullmatch(query.request_hash or "")
            and self.HASH_RE.fullmatch(query.response_hash or "")
            and metadata.get("result_category") == "not_approved"
            and normalized.get("authority_code") == "0420"
            and normalized.get("approved") is False
            and normalized.get("not_found") is True
        )

    def _blocked(self, base, reason):
        return PySifenRetryEligibility(reason=reason, **base)

    def _metadata(self, transmission):
        try:
            metadata = json.loads(transmission.metadata_json or "{}")
        except (TypeError, ValueError):
            return {}
        return metadata if isinstance(metadata, dict) else {}
