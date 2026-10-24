import re

from odoo import http
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.http import content_disposition, request

from odoo.addons.einvoice_py.services.py_fiscal_document_delivery_service import (
    PyFiscalDocumentDeliveryService,
)
from odoo.addons.einvoice_py.services.py_fiscal_email_delivery_service import (
    PyFiscalEmailDeliveryService,
)


class PyPosFiscalStatusController(http.Controller):

    @http.route("/einvoice_py_pos/fiscal/status", type="json", auth="user")
    def status(self, session_id, decision_id):
        _session, order = self._session_order(session_id, decision_id)
        return request.env["py.pos.fiscal.submission.job"].status_for_pos(order=order)

    @http.route("/einvoice_py_pos/fiscal/email", type="json", auth="user")
    def email(self, session_id, decision_id, request_id):
        _session, order = self._session_order(session_id, decision_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", str(request_id or "")):
            raise ValidationError("Fiscal email request identity is invalid.")
        job = request.env["py.pos.fiscal.submission.job"].sudo().search([
            ("order_id", "=", order.id),
        ], limit=1)
        if not job or job.document_id.state != "accepted":
            raise ValidationError("Only an accepted POS fiscal document can be emailed.")
        delivery = PyFiscalEmailDeliveryService(request.env).enqueue(
            document=job.document_id,
            mode="manual",
            request_key=f"pos:{order.id}:{request_id}",
        )
        return {"delivery_id": delivery.id, "status": "queued"}

    @http.route(
        "/einvoice_py_pos/fiscal/file/<string:decision_id>/<string:file_kind>",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def file(self, decision_id, file_kind, session_id=None, **_kwargs):
        if file_kind not in ("pdf", "xml"):
            return request.not_found()
        try:
            _session, order = self._session_order(session_id, decision_id)
            job = request.env["py.pos.fiscal.submission.job"].sudo().search([
                ("order_id", "=", order.id),
            ], limit=1)
            if not job:
                raise MissingError("Fiscal submission job not found.")
            delivery_file = PyFiscalDocumentDeliveryService(request.env).resolve_file(
                document=job.document_id.sudo(),
                file_kind=file_kind,
            )
        except (AccessError, MissingError, ValidationError, ValueError, TypeError):
            return request.not_found()
        disposition = content_disposition(delivery_file.filename)
        if file_kind == "pdf":
            disposition = disposition.replace("attachment;", "inline;", 1)
        return request.make_response(
            delivery_file.content,
            headers=[
                ("Content-Type", delivery_file.mimetype),
                ("Content-Disposition", disposition),
                ("X-Content-Type-Options", "nosniff"),
                ("Cache-Control", "private, no-store"),
            ],
        )

    def _session_order(self, session_id, decision_id):
        session = request.env["pos.session"].browse(int(session_id)).exists()
        if (
            not session
            or not session.config_id.py_fiscal_checkout_enabled
            or session.company_id not in request.env.companies
        ):
            raise AccessError("Paraguay fiscal checkout is not available for this POS session.")
        order = request.env["pos.order"].search([
            ("session_id", "=", session.id),
            ("company_id", "=", session.company_id.id),
            ("py_fiscal_decision_id", "=", str(decision_id or "")),
        ], limit=1)
        if not order:
            raise AccessError("The POS fiscal decision is outside this session.")
        return session, order
