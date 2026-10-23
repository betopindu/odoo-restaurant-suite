from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _loader_params_res_partner(self):
        params = super()._loader_params_res_partner()
        fields = params["search_params"]["fields"]
        for field_name in ("py_sifen_receiver_profile", "py_sifen_taxpayer_type"):
            if field_name not in fields:
                fields.append(field_name)
        return params

    def _get_pos_ui_res_partner(self, params):
        partners = super()._get_pos_ui_res_partner(params)
        unnamed = self.config_id.py_fiscal_unnamed_partner_id
        if unnamed and unnamed.id not in {partner["id"] for partner in partners}:
            extra = self.env["res.partner"].search_read(
                [("id", "=", unnamed.id)],
                fields=params["search_params"]["fields"],
            )
            partners.extend(extra)
        return partners
