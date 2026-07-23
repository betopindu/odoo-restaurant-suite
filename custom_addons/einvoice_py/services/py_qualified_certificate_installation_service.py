import json
from datetime import datetime, timezone

from odoo import fields

from odoo.addons.einvoice_module.services.credential_provider import (
    FiscalCredentialProviderRegistry,
)
from odoo.addons.einvoice_py.services.py_certificate_inspection_service import (
    PyCertificateInspectionService,
)


class PyQualifiedCertificateInstallationValidationService:
    """Validate an installed Paraguay PKCS#12 credential without contacting SIFEN."""

    ROLES = ("xml_signing", "mutual_tls")

    def __init__(self, env, provider_registry=None, inspection_service=None):
        self.env = env
        self.provider_registry = (
            provider_registry
            if provider_registry is not None
            else FiscalCredentialProviderRegistry(env)
        )
        self.inspection_service = (
            inspection_service
            if inspection_service is not None
            else PyCertificateInspectionService()
        )

    def validate(
        self,
        *,
        credential,
        adapter_config,
        expected_ruc,
        inspection_time=None,
    ):
        credential.ensure_one()
        adapter_config.ensure_one()
        inspected_at = inspection_time or fields.Datetime.now()
        report = self._base_report()
        report["errors"].extend(
            self._configuration_errors(credential, adapter_config)
        )
        if report["errors"]:
            return self._finish(
                credential,
                report,
                status="invalid",
                inspected_at=inspected_at,
            )

        try:
            material = self.provider_registry.get_provider(
                credential
            ).load_material(credential)
        except Exception:
            report["errors"].append(
                "Qualified certificate material could not be loaded."
            )
            return self._finish(
                credential,
                report,
                status="error",
                inspected_at=inspected_at,
            )

        if not isinstance(material, dict):
            report["errors"].append(
                "Qualified certificate material could not be loaded."
            )
            return self._finish(
                credential,
                report,
                status="error",
                inspected_at=inspected_at,
            )

        for role in self.ROLES:
            role_report = self.inspection_service.inspect(
                material_format=credential.material_format,
                role=role,
                expected_ruc=expected_ruc,
                inspection_time=inspected_at,
                bundle_bytes=material.get("pkcs12_bytes"),
                password=material.get("password"),
            )
            report["roles"][role] = role_report
            report["warnings"].extend(
                f"{role}: {warning}" for warning in role_report["warnings"]
            )
            report["errors"].extend(
                f"{role}: {error}" for error in role_report["errors"]
            )

        return self._finish(
            credential,
            report,
            status="valid" if not report["errors"] else "invalid",
            inspected_at=inspected_at,
        )

    def _configuration_errors(self, credential, adapter_config):
        errors = []
        if not credential.active:
            errors.append("Qualified certificate credential must be active.")
        if credential.provider_type != "external_secret":
            errors.append(
                "Qualified certificate credential must use the external_secret provider."
            )
        if credential.material_format != "pkcs12":
            errors.append(
                "Qualified certificate credential must use PKCS#12 material."
            )
        if not adapter_config.active:
            errors.append(
                "Qualified certificate adapter configuration must be active."
            )
        if (adapter_config.country_code or "").upper() != "PY":
            errors.append(
                "Qualified certificate adapter configuration must use country PY."
            )
        if adapter_config.credentials_mode != "external_secret":
            errors.append(
                "Qualified certificate adapter must use external_secret credentials."
            )
        if adapter_config.tenant_id != credential.tenant_id:
            errors.append(
                "Qualified certificate and adapter must belong to the same tenant."
            )
        if adapter_config.company_id != credential.company_id:
            errors.append(
                "Qualified certificate and adapter must belong to the same company."
            )
        for role in self.ROLES:
            bindings = adapter_config.credential_binding_ids.filtered(
                lambda binding: binding.role == role
            )
            if len(bindings) != 1 or bindings.credential_id != credential:
                errors.append(
                    f"Qualified certificate must be bound once to {role}."
                )
        return errors

    def _base_report(self):
        return {
            "valid": False,
            "status": "pending",
            "errors": [],
            "warnings": [],
            "roles": {},
        }

    def _finish(self, credential, report, *, status, inspected_at):
        report["status"] = status
        report["valid"] = status == "valid"
        metadata = report["roles"].get("xml_signing") or {}
        credential.write({
            "certificate_fingerprint_sha256": (
                metadata.get("certificate_fingerprint_sha256") or False
            ),
            "subject_summary": metadata.get("subject") or False,
            "issuer_summary": metadata.get("issuer") or False,
            "certificate_serial_number": (
                metadata.get("certificate_serial_number") or False
            ),
            "not_before": self._report_datetime(metadata.get("not_before")),
            "not_after": self._report_datetime(metadata.get("not_after")),
            "extracted_ruc": metadata.get("extracted_ruc") or False,
            "inspection_status": status,
            "inspected_at": self._inspection_datetime(inspected_at),
            "inspection_report_json": json.dumps(report, sort_keys=True),
        })
        return report

    def _report_datetime(self, value):
        if not value:
            return False
        return datetime.fromisoformat(value.removesuffix("Z"))

    def _inspection_datetime(self, value):
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
