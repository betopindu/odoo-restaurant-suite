from odoo import http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request

from odoo.addons.einvoice_py.services.py_sifen_ruc_query_service import (
    PySifenRucQueryService,
)


class PyPosRucLookupController(http.Controller):

    @http.route("/einvoice_py_pos/ruc/resolve", type="json", auth="user")
    def resolve(self, session_id, ruc):
        session = self._session(session_id)
        service = PySifenRucQueryService(request.env)
        result = service.resolve(
            adapter_config=request.env["fiscal.adapter.config"],
            company=session.company_id,
            ruc=ruc,
            allow_remote=False,
        )
        if result["status"] != "found":
            result = service.resolve(
                adapter_config=self._adapter(session),
                company=session.company_id,
                ruc=ruc,
                allow_remote=True,
            )
        return self._with_partner(result, session)

    @http.route("/einvoice_py_pos/ruc/manual", type="json", auth="user")
    def manual(self, session_id, ruc, name, taxpayer_type, email=None):
        session = self._session(session_id)
        result = PySifenRucQueryService(request.env).create_manual_partner(
            company=session.company_id,
            ruc=ruc,
            name=name,
            taxpayer_type=taxpayer_type,
            email=email,
        )
        return self._with_partner(result, session)

    @http.route("/einvoice_py_pos/ruc/complete", type="json", auth="user")
    def complete(self, session_id, partner_id, taxpayer_type, email=None):
        session = self._session(session_id)
        if taxpayer_type not in ("1", "2"):
            raise ValidationError("Select person or legal-entity taxpayer type.")
        partner = request.env["res.partner"].browse(int(partner_id)).exists()
        if (
            not partner
            or partner.py_sifen_receiver_profile != "taxpayer"
            or (partner.company_id and partner.company_id != session.company_id)
        ):
            raise AccessError("The selected taxpayer is outside this POS scope.")
        values = {"py_sifen_taxpayer_type": taxpayer_type}
        if email and not partner.email:
            values["email"] = email.strip()
        partner.write(values)
        return self._with_partner({
            "status": "found",
            "source": partner.py_sifen_ruc_resolution or "local",
            "partner_id": partner.id,
        }, session)

    def _session(self, session_id):
        session = request.env["pos.session"].browse(int(session_id)).exists()
        if (
            not session
            or not session.config_id.py_fiscal_checkout_enabled
            or session.company_id not in request.env.companies
        ):
            raise AccessError("Paraguay fiscal checkout is not available for this POS session.")
        return session

    def _adapter(self, session):
        config = session.config_id
        adapters = request.env["fiscal.adapter.config"].search([
            ("active", "=", True),
            ("tenant_id", "=", config.py_fiscal_tenant_id.id),
            ("company_id", "=", session.company_id.id),
            ("country_code", "=", "PY"),
            ("environment", "=", config.py_fiscal_environment),
        ])
        if len(adapters) != 1:
            raise ValidationError("Exactly one Paraguay fiscal adapter is required for Consulta RUC.")
        return adapters

    def _with_partner(self, result, session):
        result = dict(result)
        partner_id = result.get("partner_id")
        if not partner_id:
            return result
        partner = request.env["res.partner"].browse(partner_id).exists()
        if not partner:
            raise AccessError("Resolved taxpayer is not accessible.")
        fields = session._loader_params_res_partner()["search_params"]["fields"]
        records = partner.read(fields)
        result["partner"] = records[0] if records else False
        result["taxpayer_type"] = partner.py_sifen_taxpayer_type or ""
        result["email"] = partner.email or ""
        return result
