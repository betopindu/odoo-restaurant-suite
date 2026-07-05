import logging

from odoo import api, models

from odoo.addons.einvoice_py.services.py_sifen_retry_execution_service import (
    PySifenRetryExecutionService,
)


_logger = logging.getLogger(__name__)


class PySifenRetryRunner(models.AbstractModel):
    _name = "py.sifen.retry.runner"
    _description = "Paraguay SIFEN Retry Runner"

    DEFAULT_BATCH_SIZE = 10

    @api.model
    def cron_run_sifen_retries(self, limit=None):
        return self.run_sifen_retries(limit=limit)

    @api.model
    def run_sifen_retries(self, limit=None, retry_execution_service=None, **submission_kwargs):
        batch_size = self._batch_size(limit)
        execution_service = retry_execution_service or PySifenRetryExecutionService(self.env)
        results = execution_service.execute_ready(limit=batch_size, **submission_kwargs)
        self._log_summary(results)
        return results

    def _batch_size(self, limit):
        if limit is None:
            return self.DEFAULT_BATCH_SIZE
        try:
            batch_size = int(limit)
        except (TypeError, ValueError):
            return self.DEFAULT_BATCH_SIZE
        if batch_size < 1:
            return self.DEFAULT_BATCH_SIZE
        return batch_size

    def _log_summary(self, results):
        counts = {}
        for result in results:
            status = result.get("execution_status") or "unknown"
            counts[status] = counts.get(status, 0) + 1
        _logger.info(
            "Paraguay SIFEN retry runner completed.",
            extra={
                "processed_count": len(results),
                "execution_status_counts": counts,
            },
        )
