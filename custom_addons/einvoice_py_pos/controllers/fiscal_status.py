from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request


class PyPosFiscalStatusController(http.Controller):

    @http.route("/einvoice_py_pos/fiscal/status", type="json", auth="user")
    def status(self, session_id, decision_id):
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
        return request.env["py.pos.fiscal.submission.job"].status_for_pos(order=order)
