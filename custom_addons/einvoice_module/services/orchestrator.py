import json

from odoo import fields


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
        document.write(vals)
        self.create_event(document, from_state, to_state, message, actor_context=actor_context)
        return document

    def create_transmission(self, document):
        return self.env["fiscal.transmission"].create({
            "document_id": document.id,
            "attempt_number": len(document.transmission_ids) + 1,
            "transmission_type": "submit",
            "state": "accepted",
            "authority_message": "Fake accepted response",
            "started_at": fields.Datetime.now(),
            "finished_at": fields.Datetime.now(),
            "metadata_json": '{"mode": "fake", "source": "orchestration_mvp"}',
        })

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

    def process_document(self, document, actor_context=None):
        if document.state == "ready":
            self.queue(document, actor_context=actor_context)

        if document.state != "queued":
            return False

        now = fields.Datetime.now()
        self.transition_to(
            document,
            "submitted",
            "Fake fiscal document submitted.",
            actor_context=actor_context,
            extra_vals={"submitted_at": now},
        )
        self.create_transmission(document)
        self.transition_to(
            document,
            "accepted",
            "Fake fiscal document accepted.",
            actor_context=actor_context,
            extra_vals={
                "accepted_at": fields.Datetime.now(),
                "authority_status": "accepted",
                "authority_receipt_ref": f"FAKE-{document.uuid}",
            },
        )
        return True

    def process_documents(self, documents, actor_context=None):
        for document in documents:
            self.process_document(document, actor_context=actor_context)
        return True

    def process_queued(self, limit=10):
        documents = self.env["fiscal.document"].search(
            [("state", "=", "queued")],
            order="create_date asc, id asc",
            limit=limit,
        )
        return self.process_documents(documents, actor_context={"actor_type": "system"})
