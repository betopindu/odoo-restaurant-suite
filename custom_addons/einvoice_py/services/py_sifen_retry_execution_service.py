from odoo import fields

from odoo.addons.einvoice_py.services.py_sifen_retry_scheduler_service import (
    PySifenRetrySchedulerService,
)
from odoo.addons.einvoice_py.services.py_sifen_transmission_persistence_service import (
    PySifenTransmissionPersistenceService,
)


class PySifenRetryExecutionService:
    """Execute due SIFEN retries only when called explicitly."""

    def __init__(
        self,
        env,
        *,
        retry_scheduler_service=None,
        transmission_persistence_service=None,
        now_provider=None,
    ):
        self.env = env
        self.retry_scheduler_service = (
            retry_scheduler_service or PySifenRetrySchedulerService(env)
        )
        self.transmission_persistence_service = (
            transmission_persistence_service
            or PySifenTransmissionPersistenceService(env)
        )
        self.now_provider = now_provider or fields.Datetime.now

    def ready_transmissions(self, *, limit=None):
        return self.env["fiscal.transmission"].sudo().search(
            [
                ("transmission_type", "=", "submit"),
                ("state", "=", "failed_retryable"),
                (
                    "error_code",
                    "in",
                    tuple(PySifenRetrySchedulerService.RETRYABLE_SUBMISSION_STAGES),
                ),
                ("retry_state", "=", "scheduled"),
                ("next_retry_at", "!=", False),
                ("next_retry_at", "<=", self.now_provider()),
            ],
            order="next_retry_at asc, id asc",
            limit=limit,
        )

    def execute_ready(self, *, limit=None, **submission_kwargs):
        return [
            self.execute_retry(transmission, **submission_kwargs)
            for transmission in self.ready_transmissions(limit=limit)
        ]

    def execute_retry(self, transmission, **submission_kwargs):
        transmission.ensure_one()
        if not self._is_due(transmission):
            return self._result(transmission, "ignored")
        if not self.retry_scheduler_service.is_retryable(transmission):
            transmission.write({
                "retry_state": "not_retryable",
                "next_retry_at": False,
            })
            return self._result(transmission, "ignored")

        source_retry_count = transmission.retry_count
        max_retry_count = transmission.max_retry_count
        persisted = self.transmission_persistence_service.submit_and_persist(
            document=transmission.document_id,
            **submission_kwargs,
        )
        result_transmission = self.env["fiscal.transmission"].sudo().browse(
            persisted["transmission_id"]
        )

        if result_transmission != transmission:
            transmission.write({
                "retry_state": "none",
                "next_retry_at": False,
            })

        result_transmission.write({
            "retry_count": source_retry_count,
            "max_retry_count": max_retry_count,
            "retry_state": "none",
            "next_retry_at": False,
        })
        retry_result = self.retry_scheduler_service.schedule_retry(result_transmission)
        return self._result(
            result_transmission,
            "executed",
            source_transmission_id=transmission.id,
            retry_result=retry_result,
        )

    def _is_due(self, transmission):
        return (
            transmission.retry_state == "scheduled"
            and bool(transmission.next_retry_at)
            and transmission.next_retry_at <= self.now_provider()
        )

    def _result(
        self,
        transmission,
        execution_status,
        *,
        source_transmission_id=None,
        retry_result=None,
    ):
        retry_result = retry_result or {}
        return {
            "execution_status": execution_status,
            "source_transmission_id": source_transmission_id or transmission.id,
            "transmission_id": transmission.id,
            "state": transmission.state,
            "retry_status": retry_result.get("retry_status") or transmission.retry_state,
            "retry_count": transmission.retry_count,
            "max_retry_count": transmission.max_retry_count,
            "next_retry_at": transmission.next_retry_at,
        }
