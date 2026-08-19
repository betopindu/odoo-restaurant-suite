from urllib.parse import urlsplit

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_qualified_certificate_installation_service import (
    PyQualifiedCertificateInstallationValidationService,
)
from odoo.addons.einvoice_py.services.py_source_artifact_service import (
    PySourceArtifactService,
)
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)


class PySifenTestReadinessService:
    """Evaluate local SIFEN TEST submission readiness without network access."""

    STATUS_READY = "ready"
    STATUS_FISCAL_INVALID = "fiscal_configuration_invalid"
    STATUS_FISCAL_READY = "fiscal_configuration_ready"
    STATUS_CSC_MISSING = "csc_missing"
    STATUS_CERTIFICATE_MISSING = "certificate_reference_missing"
    STATUS_PASSWORD_MISSING = "certificate_password_missing"
    STATUS_CERTIFICATE_INVALID = "certificate_configuration_invalid"
    STATUS_PAYLOAD_INVALID = "payload_schema_not_ready"

    def __init__(
        self,
        env,
        certificate_validation_service=None,
        source_artifact_service=None,
        unsigned_xml_builder=None,
    ):
        self.env = env
        self.certificate_validation_service = (
            certificate_validation_service
            if certificate_validation_service is not None
            else PyQualifiedCertificateInstallationValidationService(env)
        )
        self.source_artifact_service = (
            source_artifact_service or PySourceArtifactService(env)
        )
        self.unsigned_xml_builder = unsigned_xml_builder or PyUnsignedXmlBuilder(env)

    def check(self, *, document):
        document.ensure_one()
        fiscal_errors = self._fiscal_errors(document)
        report = {
            "ready": False,
            "status": self.STATUS_FISCAL_INVALID,
            "fiscal_configuration_ready": not fiscal_errors,
            "csc_configured": False,
            "certificate_reference_configured": False,
            "certificate_password_configured": False,
            "certificate_valid": False,
            "errors": fiscal_errors,
        }
        if fiscal_errors:
            return report

        report["status"] = self.STATUS_FISCAL_READY
        csc_errors = self._csc_errors(document)
        if csc_errors:
            report["status"] = self.STATUS_CSC_MISSING
            report["errors"] = csc_errors
            return report
        report["csc_configured"] = True

        credential, credential_errors = self._credential(document)
        if credential_errors:
            report["status"] = self.STATUS_CERTIFICATE_MISSING
            report["errors"] = credential_errors
            return report
        if not (credential.secret_ref or "").strip():
            report["status"] = self.STATUS_CERTIFICATE_MISSING
            report["errors"] = [
                "SIFEN TEST PKCS#12 reference is missing.",
            ]
            return report
        report["certificate_reference_configured"] = True

        if not (credential.password_secret_ref or "").strip():
            report["status"] = self.STATUS_PASSWORD_MISSING
            report["errors"] = [
                "SIFEN TEST PKCS#12 password reference is missing.",
            ]
            return report
        report["certificate_password_configured"] = True

        try:
            certificate_report = (
                self.certificate_validation_service.validate(
                    credential=credential,
                    adapter_config=document.adapter_config_id,
                    expected_ruc=(
                        f"{document.py_issuer_id.ruc}-"
                        f"{document.py_issuer_id.ruc_dv}"
                    ),
                )
            )
        except Exception:
            certificate_report = {"valid": False}
        if not certificate_report.get("valid"):
            report["status"] = self.STATUS_CERTIFICATE_INVALID
            report["errors"] = [
                "SIFEN TEST PKCS#12 installation is not valid.",
            ]
            return report

        payload_errors = self._payload_errors(document)
        if payload_errors:
            report["status"] = self.STATUS_PAYLOAD_INVALID
            report["errors"] = payload_errors
            return report

        report.update({
            "ready": True,
            "status": self.STATUS_READY,
            "certificate_valid": True,
            "errors": [],
        })
        return report

    def _payload_errors(self, document):
        try:
            _attachment, payload = self.source_artifact_service.read_current_payload(
                document=document
            )
            self.unsigned_xml_builder.build_from_payload(payload)
        except ValidationError as error:
            return [str(error)]
        return []

    def _fiscal_errors(self, document):
        errors = []
        adapter = document.adapter_config_id
        issuer = document.py_issuer_id
        establishment = document.py_establishment_id
        point = document.py_point_of_issue_id
        timbrado = document.py_timbrado_id

        if (document.country_code or "").upper() != "PY":
            errors.append("SIFEN TEST readiness requires a Paraguay document.")
        if document.environment != "test":
            errors.append("SIFEN TEST readiness requires the TEST environment.")
        if not self._adapter_matches(document, adapter):
            errors.append("SIFEN TEST adapter configuration is incomplete.")
        if not self._issuer_matches(document, issuer):
            errors.append("SIFEN TEST issuer configuration is incomplete.")
        if not self._three_digits(
            establishment.code if establishment else ""
        ) or not self._establishment_matches(document, establishment, issuer):
            errors.append(
                "SIFEN TEST establishment must be active, scoped, and use three digits."
            )
        if not self._three_digits(
            point.code if point else ""
        ) or not self._point_matches(document, point, establishment):
            errors.append(
                "SIFEN TEST expedition point must be active, scoped, and use three digits."
            )
        if not self._timbrado_matches(
            document,
            timbrado,
            issuer,
            point,
        ):
            errors.append(
                "SIFEN TEST timbrado must equal the RUC without DV and include its start date."
            )
        return errors

    def _adapter_matches(self, document, adapter):
        if not adapter:
            return False
        try:
            endpoint = urlsplit((adapter.endpoint_base_url or "").strip())
        except ValueError:
            return False
        return bool(
            adapter.active
            and (adapter.country_code or "").upper() == "PY"
            and adapter.environment == "test"
            and adapter.tenant_id == document.tenant_id
            and adapter.company_id == document.company_id
            and adapter.sequence_id
            and endpoint.scheme == "https"
            and endpoint.netloc
            and not endpoint.username
            and not endpoint.password
            and not endpoint.query
            and not endpoint.fragment
        )

    def _issuer_matches(self, document, issuer):
        return bool(
            issuer
            and issuer.active
            and issuer.environment == "test"
            and issuer.tenant_id == document.tenant_id
            and issuer.company_id == document.company_id
            and issuer.ruc
            and issuer.ruc.isdigit()
            and len(issuer.ruc) <= 8
            and issuer.ruc_dv
            and issuer.ruc_dv.isdigit()
            and len(issuer.ruc_dv) == 1
        )

    def _establishment_matches(self, document, establishment, issuer):
        return bool(
            establishment
            and establishment.active
            and establishment.tenant_id == document.tenant_id
            and establishment.company_id == document.company_id
            and establishment.issuer_id == issuer
        )

    def _point_matches(self, document, point, establishment):
        return bool(
            point
            and point.active
            and point.tenant_id == document.tenant_id
            and point.company_id == document.company_id
            and point.establishment_id == establishment
        )

    def _timbrado_matches(self, document, timbrado, issuer, point):
        return bool(
            timbrado
            and timbrado.active
            and timbrado.environment == "test"
            and timbrado.tenant_id == document.tenant_id
            and timbrado.company_id == document.company_id
            and timbrado.document_type == document.document_type
            and issuer
            and timbrado.number == issuer.ruc
            and timbrado.valid_from
            and (
                not timbrado.allowed_point_of_issue_ids
                or point in timbrado.allowed_point_of_issue_ids
            )
        )

    def _csc_errors(self, document):
        csc = document.py_csc_id
        if not (
            csc
            and csc.active
            and csc.environment == "test"
            and csc.tenant_id == document.tenant_id
            and csc.company_id == document.company_id
            and (csc.id_csc or "").strip()
            and (csc.csc_value or "").strip()
        ):
            return ["SIFEN TEST CSC configuration is missing."]
        return []

    def _credential(self, document):
        adapter = document.adapter_config_id
        bindings = adapter.credential_binding_ids.filtered(
            lambda binding: binding.role in ("xml_signing", "mutual_tls")
        )
        signing = bindings.filtered(
            lambda binding: binding.role == "xml_signing"
        )
        mutual_tls = bindings.filtered(
            lambda binding: binding.role == "mutual_tls"
        )
        if (
            len(signing) != 1
            or len(mutual_tls) != 1
            or signing.credential_id != mutual_tls.credential_id
        ):
            return None, [
                "SIFEN TEST PKCS#12 credential bindings are missing.",
            ]
        credential = signing.credential_id
        if not (
            credential.active
            and credential.tenant_id == document.tenant_id
            and credential.company_id == document.company_id
            and credential.provider_type == "external_secret"
            and credential.material_format == "pkcs12"
        ):
            return None, [
                "SIFEN TEST PKCS#12 credential configuration is invalid.",
            ]
        return credential, []

    def _three_digits(self, value):
        return bool(value and value.isdigit() and len(value) == 3)
