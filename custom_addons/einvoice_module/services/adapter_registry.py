from dataclasses import dataclass, field


@dataclass
class FiscalAdapterResult:
    outcome: str
    authority_status_code: str = ""
    authority_message: str = ""
    country_identifier: str = ""
    authority_receipt_ref: str = ""
    retryable: bool = False
    retry_after_seconds: int = 0
    metadata_json: dict = field(default_factory=dict)


class FiscalAdapter:
    code = "base"

    def __init__(self, env):
        self.env = env

    def validate(self, document):
        return True

    def prepare_payload(self, document):
        return {}

    def submit(self, document):
        raise NotImplementedError

    def parse_response(self, response):
        return response


class FakeAdapter(FiscalAdapter):
    code = "fake"

    def submit(self, document):
        outcome = self._outcome_from_document(document)
        country_identifier = document.country_identifier or f"FAKE-ID-{document.uuid}"
        return FiscalAdapterResult(
            outcome=outcome,
            authority_status_code=outcome,
            authority_message=self._message_from_outcome(outcome),
            country_identifier=country_identifier if outcome == "accepted" else "",
            authority_receipt_ref=f"FAKE-{document.uuid}",
            retryable=outcome == "failed_retryable",
            retry_after_seconds=300 if outcome == "failed_retryable" else 0,
            metadata_json={
                "mode": "fake",
                "adapter_code": self.code,
                "source": "adapter_registry_mvp",
                "matched_outcome": outcome,
            },
        )

    def _outcome_from_document(self, document):
        name = (document.name or "").upper()
        if "REJECT" in name:
            return "rejected"
        if "RETRY" in name:
            return "failed_retryable"
        if "FAIL" in name:
            return "failed_final"
        if "MANUAL" in name:
            return "manual_review"
        return "accepted"

    def _message_from_outcome(self, outcome):
        return {
            "accepted": "Fake accepted response",
            "rejected": "Fake rejected response",
            "failed_retryable": "Fake retryable failure response",
            "failed_final": "Fake final failure response",
            "manual_review": "Fake manual review response",
        }.get(outcome, "Fake unknown response")


class PyAdapter(FakeAdapter):
    code = "py"


class CrAdapter(FakeAdapter):
    code = "cr"


class FiscalAdapterRegistry:
    ADAPTERS = {
        "fake": FakeAdapter,
        "py": PyAdapter,
        "cr": CrAdapter,
    }

    COUNTRY_ADAPTERS = {
        "PY": "py",
        "CR": "cr",
    }

    def __init__(self, env):
        self.env = env

    def get_adapter(self, document):
        adapter_code = (document.adapter_code or "").lower()
        if not adapter_code:
            adapter_code = self.COUNTRY_ADAPTERS.get((document.country_code or "").upper(), "fake")
        adapter_class = self.ADAPTERS.get(adapter_code, FakeAdapter)
        return adapter_class(self.env)
