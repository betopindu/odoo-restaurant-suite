import json

from psycopg2 import errors

from odoo.exceptions import AccessError, ValidationError

from .py_sifen_ambiguous_reconciliation_service import PySifenReconciliationService
from .py_sifen_manual_retry_service import PySifenManualRetryService
from .py_sifen_retry_signing_time_service import PySifenRetrySigningTimeService
from .py_sifen_test_readiness_service import PySifenTestReadinessService
from .py_sifen_transmission_persistence_service import PySifenTransmissionPersistenceService
from .py_source_artifact_service import PySourceArtifactService


class PySifenOperatorService:
    """Thin, permission-aware UI boundary over the existing SIFEN services."""

    OPERATOR_GROUP = "einvoice_py.group_py_fiscal_operator"

    def __init__(
        self,
        env,
        *,
        readiness_service=None,
        persistence_service=None,
        manual_retry_service=None,
        reconciliation_service=None,
        source_artifact_service=None,
        signing_time_service=None,
    ):
        self.env = env
        self.readiness_service = readiness_service or PySifenTestReadinessService(env)
        self.persistence_service = persistence_service or PySifenTransmissionPersistenceService(env)
        self.manual_retry_service = manual_retry_service or PySifenManualRetryService(env)
        self.reconciliation_service = reconciliation_service or PySifenReconciliationService(env)
        self.source_artifact_service = source_artifact_service or PySourceArtifactService(env)
        self.signing_time_service = signing_time_service or PySifenRetrySigningTimeService(env)

    def submission_mode(self, *, document):
        self._validate_scope(document)
        if document.state == "ready":
            if self._submissions(document):
                raise ValidationError(
                    "A prepared document with submission history cannot use initial submission."
                )
            return "initial"
        timestamp = self.signing_time_service.fresh(document=document)
        self.manual_retry_service.validate(
            document=document,
            signing_timestamp=timestamp,
        )
        return "manual_retry"

    def submit(self, *, document):
        self._require_operator()
        # Submission concurrency belongs to the durable pre-POST transaction.
        # Holding this caller-transaction row lock would make the independent
        # durable cursor conflict with the same legitimate request.
        mode = self.submission_mode(document=document)
        readiness = self.readiness_service.check(document=document)
        if not readiness.get("ready"):
            errors = readiness.get("errors") or ["SIFEN readiness validation failed."]
            raise ValidationError("\n".join(errors))
        if mode == "manual_retry":
            response = self.manual_retry_service.retry(document=document)
        else:
            _attachment, payload = self.source_artifact_service.read_current_payload(
                document=document
            )
            response = self.persistence_service.submit_and_persist(
                document=document,
                payload=payload,
                signing_timestamp=self.signing_time_service.fresh(document=document),
            )
        return self._safe_submission_result(response, mode=mode)

    def can_reconcile(self, *, document):
        self._validate_scope(document)
        if document.state == "accepted":
            return False
        completed = self.env["fiscal.transmission"].sudo().search_count([
            ("document_id", "=", document.id),
            ("transmission_type", "=", "status_query"),
            "|",
            ("state", "=", "accepted"),
            ("error_code", "=", "reconciliation_not_found"),
        ])
        if completed:
            return False
        return bool(self._ambiguous_submissions(document))

    def reconcile(self, *, document):
        self._require_operator()
        self._lock(document)
        if not self.can_reconcile(document=document):
            raise ValidationError(
                "Consulta DE recovery requires an unresolved ambiguous submission."
            )
        return self.reconciliation_service.reconcile(document=document)

    def guidance(self, *, document):
        try:
            if self.can_reconcile(document=document):
                return "consulta_required", "Consulta DE is required before any resend."
            mode = self.submission_mode(document=document)
            if mode == "initial":
                return "submit_ready", "Ready for explicit operator submission."
            return "manual_retry_allowed", "A guarded manual retry is available."
        except (AccessError, ValidationError):
            return "blocked", "No network operation is currently authorized."

    def _safe_submission_result(self, response, *, mode):
        result = response.get("result") if isinstance(response, dict) else None
        result = result if isinstance(result, dict) else {}
        return {
            "operation": mode,
            "transmission_id": int((response or {}).get("transmission_id") or 0),
            "submission_status": result.get("submission_status") or "",
            "authority_code": result.get("authority_code") or "",
            "authority_message": result.get("authority_message") or "",
            "authority_protocol": result.get("authority_receipt_ref") or "",
            "ambiguous": bool(result.get("ambiguous")),
            "http_status": int(result.get("http_status") or 0),
            "duration_ms": max(0, int(result.get("duration_ms") or 0)),
        }

    def _require_operator(self):
        if not self.env.user.has_group(self.OPERATOR_GROUP):
            raise AccessError("Only an authorized fiscal operator may contact SIFEN.")

    def _validate_scope(self, document):
        document.ensure_one()
        if (document.country_code or "").upper() != "PY":
            raise ValidationError("The operator workflow requires a Paraguay document.")
        if document.environment not in ("test", "production"):
            raise ValidationError("The fiscal environment is invalid.")
        if document.company_id not in self.env.companies:
            raise AccessError("The fiscal document company is not active for this operator.")
        if document.tenant_id not in self.env.user.allowed_fiscal_tenant_ids:
            raise AccessError("The fiscal document tenant is not allowed for this operator.")

    def _lock(self, document):
        try:
            self.env.cr.execute(
                "SELECT id FROM fiscal_document WHERE id = %s FOR UPDATE NOWAIT",
                [document.id],
            )
        except errors.LockNotAvailable:
            raise ValidationError(
                "A SIFEN operator action is already in progress for this document."
            ) from None
        if not self.env.cr.fetchone():
            raise ValidationError("The fiscal document no longer exists.")

    def _submissions(self, document):
        return self.env["fiscal.transmission"].sudo().search([
            ("document_id", "=", document.id),
            ("transmission_type", "=", "submit"),
        ])

    def _ambiguous_submissions(self, document):
        return self._submissions(document).filtered(self._is_ambiguous)

    @staticmethod
    def _is_ambiguous(transmission):
        if transmission.state in ("sent", "manual_review") or transmission.error_code == "ambiguous_submission":
            try:
                metadata = json.loads(transmission.metadata_json or "{}")
            except (TypeError, ValueError):
                metadata = {}
            return transmission.error_code == "ambiguous_submission" or metadata.get("ambiguous") is True
        return False
