from odoo import fields, models


class FiscalTransmission(models.Model):
    _inherit = "fiscal.transmission"

    country_code = fields.Char(size=2, index=True)
    environment = fields.Selection(
        [("test", "Test"), ("production", "Production")],
        index=True,
    )
    country_identifier = fields.Char(index=True)
    signed_xml_sha256 = fields.Char(index=True)
    qr_hash = fields.Char(index=True)
