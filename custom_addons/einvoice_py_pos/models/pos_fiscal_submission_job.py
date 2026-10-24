import logging

from odoo import api, fields, models, registry, SUPERUSER_ID
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_operator_service import (
    PySifenOperatorService,
)


_logger = logging.getLogger(__name__)


class PyPosFiscalSubmissionJob(models.Model):
    _name = "py.pos.fiscal.submission.job"
    _description = "Paraguay POS Fiscal Submission Job"
    _order = "id"

    order_id = fields.Many2one("pos.order", required=True, readonly=True, ondelete="restrict")
    document_id = fields.Many2one(
        "fiscal.document", required=True, readonly=True, ondelete="restrict", index=True
    )
    config_id = fields.Many2one("pos.config", required=True, readonly=True, ondelete="restrict")
    company_id = fields.Many2one("res.company", required=True, readonly=True, index=True)
    tenant_id = fields.Many2one("fiscal.tenant", required=True, readonly=True, index=True)
    operator_user_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    state = fields.Selection(
        [
            ("queued", "Queued"),
            ("processing", "Processing / manual review if interrupted"),
            ("completed", "Completed"),
            ("failed", "Failed - manual action required"),
        ],
        required=True,
        default="queued",
        readonly=True,
        index=True,
    )
    attempt_count = fields.Integer(default=0, readonly=True)
    claimed_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)
    transmission_id = fields.Many2one("fiscal.transmission", readonly=True, ondelete="restrict")
    submission_status = fields.Char(readonly=True)
    authority_code = fields.Char(readonly=True)
    authority_message = fields.Char(readonly=True)
    authority_protocol = fields.Char(readonly=True)
    ambiguous = fields.Boolean(readonly=True)
    error_detail = fields.Char(readonly=True)

    _sql_constraints = [
        ("document_once", "unique(document_id)", "A POS fiscal document can only be queued once."),
        ("order_once", "unique(order_id)", "A POS order can only have one fiscal submission job."),
    ]

    @api.model
    def enqueue(self, *, order, document):
        order.ensure_one()
        document.ensure_one()
        config = order.config_id
        if not config.py_fiscal_auto_submit_enabled:
            return self.browse()
        existing = self.sudo().search([
            "|", ("order_id", "=", order.id), ("document_id", "=", document.id),
        ], limit=1)
        if existing:
            return existing
        if document.state != "ready":
            raise ValidationError("Automatic POS submission requires a ready fiscal document.")
        if self.env["fiscal.transmission"].sudo().search_count([
            ("document_id", "=", document.id), ("transmission_type", "=", "submit"),
        ]):
            raise ValidationError("A fiscal document with submission history cannot be queued.")
        return self.sudo().create({
            "order_id": order.id,
            "document_id": document.id,
            "config_id": config.id,
            "company_id": order.company_id.id,
            "tenant_id": document.tenant_id.id,
            "operator_user_id": config.py_fiscal_auto_submit_user_id.id,
        })

    @api.model
    def cron_process_queued(self, limit=10):
        job_ids = self.sudo().search([("state", "=", "queued")], limit=limit, order="id").ids
        results = []
        for job_id in job_ids:
            results.append(self._process_in_durable_boundary(job_id))
        return results

    @api.model
    def _process_in_durable_boundary(self, job_id):
        database = self.env.cr.dbname
        with registry(database).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            job = env[self._name].browse(job_id).exists()
            if not job or not job._claim_once():
                return {"job_id": job_id, "status": "skipped"}
            operator_id = job.operator_user_id.id
            company_id = job.company_id.id
            cr.commit()
        try:
            with registry(database).cursor() as cr:
                env = api.Environment(cr, operator_id, {"allowed_company_ids": [company_id]})
                job = env[self._name].browse(job_id).exists()
                result = job._execute_once()
                cr.commit()
                return result
        except Exception as exc:  # cron boundary must leave a durable manual stop
            _logger.exception("Automatic POS SIFEN submission stopped; manual action is required.")
            with registry(database).cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                job = env[self._name].browse(job_id).exists()
                if job:
                    job.write({
                        "state": "failed",
                        "finished_at": fields.Datetime.now(),
                        "error_detail": self._safe_error(exc),
                    })
                cr.commit()
            return {"job_id": job_id, "status": "failed"}

    def _claim_once(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM py_pos_fiscal_submission_job "
            "WHERE id = %s AND state = 'queued' FOR UPDATE SKIP LOCKED",
            [self.id],
        )
        if not self.env.cr.fetchone():
            return False
        self.write({
            "state": "processing",
            "attempt_count": 1,
            "claimed_at": fields.Datetime.now(),
        })
        self.flush_recordset(["state", "attempt_count", "claimed_at"])
        return True

    def _execute_once(self, operator_service=None):
        self.ensure_one()
        if self.state != "processing" or self.attempt_count != 1:
            raise ValidationError("The POS fiscal submission job is not executable.")
        service = operator_service or PySifenOperatorService(self.env)
        result = service.submit(document=self.document_id)
        transmission = self.env["fiscal.transmission"].sudo().browse(
            result.get("transmission_id")
        ).exists()
        if transmission:
            transmission.write({
                "max_retry_count": 0,
                "retry_state": "not_retryable",
                "next_retry_at": False,
            })
        self.sudo().write({
            "state": "completed",
            "finished_at": fields.Datetime.now(),
            "transmission_id": transmission.id,
            "submission_status": result.get("submission_status") or "",
            "authority_code": result.get("authority_code") or "",
            "authority_message": result.get("authority_message") or "",
            "authority_protocol": result.get("authority_protocol") or "",
            "ambiguous": bool(result.get("ambiguous")),
        })
        return {"job_id": self.id, "status": "completed", **result}

    @staticmethod
    def _safe_error(exc):
        label = exc.__class__.__name__
        return (label + ": automatic submission did not reach a safely classified completion.")[:255]
