import json
from datetime import timedelta

from odoo import fields
from odoo.addons.einvoice_module.services.adapter_registry import FiscalAdapterRegistry
from odoo.addons.einvoice_module.services.validation import FiscalDocumentValidationService
from odoo.exceptions import ValidationError


class FiscalOrchestrator:
    """Minimal fake fiscal orchestration service for the core MVP."""

    def __init__(self, env):
        self.env = env

    def _normalize_actor_context(self, actor_context=None):
        actor_context = actor_context or {}
        actor_type = actor_context.get("actor_type") or "system"
        if actor_type not in ("user", "system", "api"):
            actor_type = "system"
        user_id = actor_context.get("user_id") if actor_type == "user" else False
        return {
            "actor_type": actor_type,
            "user_id": user_id,
            "metadata": actor_context.get("metadata"),
        }

    def create_event(self, document, from_state, to_state, message, actor_context=None):
        actor = self._normalize_actor_context(actor_context)
        vals = {
            "document_id": document.id,
            "event_type": "state_transition",
            "from_state": from_state,
            "to_state": to_state,
            "actor_type": actor["actor_type"],
            "user_id": actor["user_id"],
            "occurred_at": fields.Datetime.now(),
            "message": message,
        }
        if actor["metadata"]:
            vals["metadata_json"] = json.dumps(actor["metadata"], sort_keys=True)
        return self.env["fiscal.event"].create(vals)

    def transition_to(self, document, to_state, message, actor_context=None, extra_vals=None):
        from_state = document.state
        vals = {"state": to_state}
        if extra_vals:
            vals.update(extra_vals)
        document.with_context(einvoice_skip_fiscal_document_lock=True).write(vals)
        self.create_event(document, from_state, to_state, message, actor_context=actor_context)
        return document

    def create_transmission(self, document, result):
        metadata_json = json.dumps(result.metadata_json, sort_keys=True) if result.metadata_json else False
        now = fields.Datetime.now()
        retry_after_seconds = result.retry_after_seconds or 300
        next_retry_at = False
        if result.outcome == "failed_retryable":
            next_retry_at = now + timedelta(seconds=retry_after_seconds)
        return self.env["fiscal.transmission"].create({
            "document_id": document.id,
            "attempt_number": self._next_attempt_number(document),
            "transmission_type": "submit",
            "state": self._transmission_state_from_outcome(result.outcome),
            "authority_status_code": result.authority_status_code,
            "authority_message": result.authority_message,
            "started_at": now,
            "finished_at": fields.Datetime.now(),
            "next_retry_at": next_retry_at,
            "metadata_json": metadata_json,
        })

    def create_adapter_response_attachment(self, document, transmission, result):
        payload = {
            "outcome": result.outcome,
            "authority_status_code": result.authority_status_code,
            "authority_message": result.authority_message,
            "country_identifier": result.country_identifier,
            "authority_receipt_ref": result.authority_receipt_ref,
            "retryable": result.retryable,
            "retry_after_seconds": result.retry_after_seconds,
            "metadata_json": result.metadata_json,
        }
        return self.env["fiscal.attachment"].sudo().create_json_payload_attachment(
            document,
            "authority_response",
            (
                f"{document.uuid}-adapter-response-attempt-"
                f"{transmission.attempt_number}.json"
            ),
            payload,
            transmission=transmission,
        )

    def _next_attempt_number(self, document):
        attempts = document.transmission_ids.mapped("attempt_number")
        return (max(attempts) if attempts else 0) + 1

    def _get_adapter(self, document):
        return FiscalAdapterRegistry(self.env).get_adapter(document)

    def _validate_before_submit(self, document, actor_context=None):
        result = FiscalDocumentValidationService().validate(document)
        if result.is_valid:
            return True

        self.transition_to(
            document,
            "validation_error",
            f"Fiscal document validation failed: {result.summary()}",
            actor_context=actor_context,
        )
        return False

    def _transmission_state_from_outcome(self, outcome):
        return {
            "accepted": "accepted",
            "rejected": "rejected",
            "failed_retryable": "failed_retryable",
            "failed_final": "failed_final",
            "manual_review": "manual_review",
        }.get(outcome, "failed_final")

    def _document_state_from_outcome(self, outcome):
        return {
            "accepted": "accepted",
            "rejected": "rejected",
            "failed_retryable": "failed_retryable",
            "failed_final": "failed_final",
            "manual_review": "manual_review",
        }.get(outcome, "failed_final")

    def _transition_message_from_outcome(self, outcome):
        return {
            "accepted": "Fiscal document accepted.",
            "rejected": "Fiscal document rejected.",
            "failed_retryable": "Fiscal document failed with a retryable error.",
            "failed_final": "Fiscal document failed with a final error.",
            "manual_review": "Fiscal document requires manual review.",
        }.get(outcome, "Fiscal document failed.")

    def _extra_vals_from_result(self, result):
        vals = {
            "authority_status": result.authority_status_code,
            "authority_receipt_ref": result.authority_receipt_ref,
        }
        if result.country_identifier:
            vals["country_identifier"] = result.country_identifier
        if result.outcome == "accepted":
            vals["accepted_at"] = fields.Datetime.now()
        elif result.outcome == "rejected":
            vals["rejected_at"] = fields.Datetime.now()
        return vals

    def mark_ready(self, documents, actor_context=None):
        for document in documents:
            if document.state == "draft":
                self.transition_to(
                    document,
                    "ready",
                    "Document marked ready for fiscal processing.",
                    actor_context=actor_context,
                )
        return True

    def queue(self, documents, actor_context=None):
        for document in documents:
            if document.state == "ready":
                self.transition_to(
                    document,
                    "queued",
                    "Document queued for fiscal processing.",
                    actor_context=actor_context,
                )
        return True

    def retry_validation_error(self, documents, actor_context=None):
        if any(document.state != "validation_error" for document in documents):
            raise ValidationError(
                "Only fiscal documents in validation error can be requeued."
            )
        for document in documents:
            self.transition_to(
                document,
                "queued",
                "Validation error resolved and document requeued",
                actor_context=actor_context,
            )
        return True

    def _resolve_manual_review(self, documents, to_state, message, actor_context=None):
        if any(document.state != "manual_review" for document in documents):
            raise ValidationError(
                "Only fiscal documents in manual review can be resolved."
            )
        for document in documents:
            self.transition_to(
                document,
                to_state,
                message,
                actor_context=actor_context,
            )
        return True

    def retry_manual_review(self, documents, actor_context=None):
        return self._resolve_manual_review(
            documents,
            "queued",
            "Manual review resolved by retry",
            actor_context=actor_context,
        )

    def fail_manual_review(self, documents, actor_context=None):
        return self._resolve_manual_review(
            documents,
            "failed_final",
            "Manual review resolved as failed final",
            actor_context=actor_context,
        )

    def cancel_manual_review(self, documents, actor_context=None):
        return self._resolve_manual_review(
            documents,
            "cancelled",
            "Manual review cancelled",
            actor_context=actor_context,
        )

    def process_document(self, document, actor_context=None):
        if document.state == "ready":
            self.queue(document, actor_context=actor_context)
        elif document.state == "failed_retryable":
            self.transition_to(
                document,
                "queued",
                "Retryable fiscal document requeued.",
                actor_context=actor_context,
            )

        if document.state != "queued":
            return False

        if not self._validate_before_submit(document, actor_context=actor_context):
            return False

        now = fields.Datetime.now()
        self.transition_to(
            document,
            "submitted",
            "Fiscal document submitted.",
            actor_context=actor_context,
            extra_vals={"submitted_at": now},
        )
        result = self._get_adapter(document).submit(document)
        transmission = self.create_transmission(document, result)
        self.create_adapter_response_attachment(document, transmission, result)
        self.transition_to(
            document,
            self._document_state_from_outcome(result.outcome),
            self._transition_message_from_outcome(result.outcome),
            actor_context=actor_context,
            extra_vals=self._extra_vals_from_result(result),
        )
        return True

    def process_documents(self, documents, actor_context=None):
        for document in documents:
            self.process_document(document, actor_context=actor_context)
        return True

    def process_queued(self, limit=10):
        queued_documents = self.env["fiscal.document"].search(
            [("state", "=", "queued")],
            order="create_date asc, id asc",
            limit=limit,
        )
        remaining_limit = max(limit - len(queued_documents), 0)
        retry_documents = self.env["fiscal.document"].browse()
        if remaining_limit:
            now = fields.Datetime.now()
            retry_transmissions = self.env["fiscal.transmission"].search(
                [
                    ("document_id.state", "=", "failed_retryable"),
                    ("state", "=", "failed_retryable"),
                    ("next_retry_at", "!=", False),
                    ("next_retry_at", "<=", now),
                ],
                order="next_retry_at asc, id asc",
                limit=remaining_limit,
            )
            retry_documents = retry_transmissions.mapped("document_id")

        documents = queued_documents | retry_documents
        return self.process_documents(documents, actor_context={"actor_type": "system"})
