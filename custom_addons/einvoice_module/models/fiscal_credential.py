from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FiscalCredential(models.Model):
    _name = "fiscal.credential"
    _description = "Fiscal Credential Reference"
    _order = "tenant_id, company_id, name"

    name = fields.Char(required=True)
    tenant_id = fields.Many2one(
        "fiscal.tenant",
        required=True,
        index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)
    provider_type = fields.Selection(
        [
            ("external_secret", "External Secret"),
            ("encrypted_odoo_storage", "Encrypted Odoo Storage"),
            ("kms", "KMS"),
            ("pkcs11", "PKCS#11 / HSM"),
        ],
        required=True,
    )
    material_format = fields.Selection(
        [
            ("pkcs12", "PKCS#12"),
            ("pem_pair", "PEM Certificate and Key"),
            ("pkcs11", "PKCS#11 Key"),
            ("provider_managed", "Provider-Managed Key"),
        ],
        required=True,
    )
    secret_ref = fields.Char(required=True)
    password_secret_ref = fields.Char()

    certificate_fingerprint_sha256 = fields.Char(size=64, index=True, readonly=True)
    subject_summary = fields.Char(readonly=True)
    issuer_summary = fields.Char(readonly=True)
    certificate_serial_number = fields.Char(readonly=True)
    not_before = fields.Datetime(readonly=True)
    not_after = fields.Datetime(readonly=True)
    extracted_ruc = fields.Char(readonly=True)
    inspection_status = fields.Selection(
        [
            ("pending", "Pending"),
            ("valid", "Valid"),
            ("invalid", "Invalid"),
            ("error", "Error"),
        ],
        default="pending",
        required=True,
        readonly=True,
    )
    inspected_at = fields.Datetime(readonly=True)
    inspection_report_json = fields.Text(readonly=True)

    binding_ids = fields.One2many(
        "fiscal.adapter.credential.binding",
        "credential_id",
        string="Adapter Role Bindings",
    )

    @api.constrains("provider_type", "material_format")
    def _check_provider_material_consistency(self):
        for credential in self:
            if (
                credential.provider_type == "pkcs11"
                and credential.material_format != "pkcs11"
            ):
                raise ValidationError(
                    "PKCS#11 credentials must use the PKCS#11 material format."
                )
            if (
                credential.material_format == "pkcs11"
                and credential.provider_type != "pkcs11"
            ):
                raise ValidationError(
                    "PKCS#11 material format requires the PKCS#11 provider."
                )
            if (
                credential.provider_type == "kms"
                and credential.material_format != "provider_managed"
            ):
                raise ValidationError(
                    "KMS credentials must use the provider-managed material format."
                )
            if (
                credential.material_format == "provider_managed"
                and credential.provider_type != "kms"
            ):
                raise ValidationError(
                    "Provider-managed material format requires the KMS provider."
                )
