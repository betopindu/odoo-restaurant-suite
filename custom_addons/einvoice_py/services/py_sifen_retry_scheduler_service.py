import json
from datetime import timedelta

from odoo import fields


class PySifenRetrySchedulerService:
    """Schedule retryable SIFEN transport failures without executing them."""

    BASE_DELAY_SECONDS = 300
    MAX_DELAY_SECONDS = 3600
    DEFAULT_MAX_RETRY_COUNT = 3
    RETRYABLE_TRANSPORT_CATEGORIES = {
        "connection_failure",
        "tls_failure",
        "transport_failure",
    }
    RETRYABLE_SUBMISSION_STAGES = {
        "test_submission",
        "production_submission",
    }

    def __init__(
        self,
        env,
        *,
        base_delay_seconds=None,
        max_delay_seconds=None,
        default_max_retry_count=None,
        now_provider=None,
    ):
        self.env = env
        self.base_delay_seconds = base_delay_seconds or self.BASE_DELAY_SECONDS
        self.max_delay_seconds = max_delay_seconds or self.MAX_DELAY_SECONDS
        self.default_max_retry_count = default_max_retry_count or self.DEFAULT_MAX_RETRY_COUNT
        self.now_provider = now_provider or fields.Datetime.now

    def schedule_retry(self, transmission):
        transmission.ensure_one()
        if not self.is_retryable(transmission):
            transmission.write({
                "retry_state": "not_retryable",
                "next_retry_at": False,
            })
            return self._result(transmission, "not_retryable")
        if transmission.retry_state == "scheduled" and transmission.next_retry_at:
            return self._result(transmission, "scheduled")

        max_retry_count = transmission.max_retry_count or self.default_max_retry_count
        if transmission.retry_count >= max_retry_count:
            transmission.write({
                "retry_state": "exhausted",
                "next_retry_at": False,
            })
            return self._result(transmission, "exhausted")

        delay_seconds = self._delay_seconds(transmission.retry_count)
        transmission.write({
            "retry_count": transmission.retry_count + 1,
            "max_retry_count": max_retry_count,
            "retry_state": "scheduled",
            "next_retry_at": self.now_provider() + timedelta(seconds=delay_seconds),
        })
        return self._result(transmission, "scheduled")

    def is_retryable(self, transmission):
        transmission.ensure_one()
        if transmission.state != "failed_retryable":
            return False
        if transmission.transmission_type != "submit":
            return False
        if transmission.error_code not in self.RETRYABLE_SUBMISSION_STAGES:
            return False
        metadata = self._metadata(transmission)
        if not metadata.get("retryable"):
            return False
        return metadata.get("retry_category") in self.RETRYABLE_TRANSPORT_CATEGORIES

    def _delay_seconds(self, retry_count):
        return min(
            self.base_delay_seconds * (2 ** retry_count),
            self.max_delay_seconds,
        )

    def _metadata(self, transmission):
        if not transmission.metadata_json:
            return {}
        try:
            return json.loads(transmission.metadata_json)
        except (TypeError, ValueError):
            return {}

    def _result(self, transmission, retry_status):
        return {
            "transmission_id": transmission.id,
            "retry_status": retry_status,
            "retry_count": transmission.retry_count,
            "max_retry_count": transmission.max_retry_count,
            "next_retry_at": transmission.next_retry_at,
        }
