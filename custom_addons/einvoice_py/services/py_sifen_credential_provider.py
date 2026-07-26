import re
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.exceptions import UnsupportedAlgorithm

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_module.services.credential_provider import (
    FiscalCredentialProviderRegistry,
)
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenTestSubmissionService,
)


class PySifenCredentialError(ValidationError):
    """Base error for safe Paraguay SIFEN credential resolution failures."""


class PySifenCredentialConfigurationError(PySifenCredentialError):
    """Paraguay SIFEN credential configuration is incomplete or unsupported."""


class PySifenCredentialScopeError(PySifenCredentialError):
    """Paraguay SIFEN credential configuration crosses fiscal scope."""


class PySifenCredentialMaterialError(PySifenCredentialError):
    """Paraguay SIFEN secret material could not be loaded safely."""


class PySifenRuntimeCredentials:
    """Transient SIFEN credentials whose string forms never expose contents."""

    __slots__ = (
        "adapter_config",
        "xml_signing_credential",
        "mutual_tls_credential",
        "signing_certificate_bytes",
        "signing_private_key_bytes",
        "signing_private_key_password",
        "csc_id",
        "csc_value",
        "endpoint_url",
        "timeout_seconds",
    )

    def __init__(
        self,
        *,
        adapter_config,
        xml_signing_credential,
        mutual_tls_credential,
        signing_certificate_bytes,
        signing_private_key_bytes,
        signing_private_key_password,
        csc_id,
        csc_value,
        endpoint_url,
        timeout_seconds,
    ):
        self.adapter_config = adapter_config
        self.xml_signing_credential = xml_signing_credential
        self.mutual_tls_credential = mutual_tls_credential
        self.signing_certificate_bytes = signing_certificate_bytes
        self.signing_private_key_bytes = signing_private_key_bytes
        self.signing_private_key_password = signing_private_key_password
        self.csc_id = csc_id
        self.csc_value = csc_value
        self.endpoint_url = endpoint_url
        self.timeout_seconds = timeout_seconds

    def __repr__(self):
        return "<PySifenRuntimeCredentials [REDACTED]>"

    def __str__(self):
        return "<PySifenRuntimeCredentials [REDACTED]>"


class PySifenCredentialProvider:
    """Resolve tenant-safe Paraguay configuration into transient credentials."""

    SUPPORTED_MATERIAL_FORMATS = {"pem_pair", "pkcs12"}
    RUC_PATTERN = re.compile(r"^(?:RUC)?(\d+)(?:-(\d))?$", re.IGNORECASE)

    def __init__(self, env, provider_registry=None):
        self.env = env
        self.provider_registry = provider_registry or FiscalCredentialProviderRegistry(env)

    def resolve(self, *, document):
        document.ensure_one()
        adapter = self._adapter(document)
        signing_credential = self._role_credential(adapter, "xml_signing")
        mutual_tls_credential = self._role_credential(adapter, "mutual_tls")
        self._validate_credential(document, signing_credential)
        self._validate_credential(document, mutual_tls_credential)
        certificate_bytes, private_key_bytes, password = self._signing_material(
            signing_credential
        )
        csc_id, csc_value = self._csc(document)
        endpoint_url = self._endpoint(adapter)
        timeout_seconds = (
            adapter.timeout_seconds
            if adapter.timeout_seconds and adapter.timeout_seconds > 0
            else PySifenTestSubmissionService.DEFAULT_TIMEOUT_SECONDS
        )
        return PySifenRuntimeCredentials(
            adapter_config=adapter,
            xml_signing_credential=signing_credential,
            mutual_tls_credential=mutual_tls_credential,
            signing_certificate_bytes=certificate_bytes,
            signing_private_key_bytes=private_key_bytes,
            signing_private_key_password=password,
            csc_id=csc_id,
            csc_value=csc_value,
            endpoint_url=endpoint_url,
            timeout_seconds=timeout_seconds,
        )

    def _adapter(self, document):
        if (document.country_code or "").upper() != "PY":
            raise PySifenCredentialConfigurationError(
                "Paraguay SIFEN credential resolution requires a Paraguay document."
            )
        adapter = document.adapter_config_id
        if not adapter:
            raise PySifenCredentialConfigurationError(
                "Paraguay SIFEN adapter configuration is required."
            )
        if not adapter.active:
            raise PySifenCredentialConfigurationError(
                "Paraguay SIFEN adapter configuration must be active."
            )
        if (adapter.country_code or "").upper() != "PY":
            raise PySifenCredentialConfigurationError(
                "Paraguay SIFEN adapter configuration must use country PY."
            )
        if adapter.tenant_id != document.tenant_id:
            raise PySifenCredentialScopeError(
                "Paraguay SIFEN adapter and document must belong to the same tenant."
            )
        if adapter.company_id != document.company_id:
            raise PySifenCredentialScopeError(
                "Paraguay SIFEN adapter and document must belong to the same company."
            )
        if adapter.environment != document.environment:
            raise PySifenCredentialScopeError(
                "Paraguay SIFEN adapter and document must use the same environment."
            )
        return adapter

    def _role_credential(self, adapter, role):
        bindings = adapter.credential_binding_ids.filtered(
            lambda binding: binding.role == role and binding.credential_id.active
        )
        if len(bindings) != 1:
            role_label = "XML signing" if role == "xml_signing" else "mutual TLS"
            raise PySifenCredentialConfigurationError(
                f"Exactly one active Paraguay SIFEN {role_label} credential is required."
            )
        return bindings.credential_id

    def _validate_credential(self, document, credential):
        if not credential.active:
            raise PySifenCredentialConfigurationError(
                "Paraguay SIFEN credentials must be active."
            )
        if credential.tenant_id != document.tenant_id:
            raise PySifenCredentialScopeError(
                "Paraguay SIFEN credential and document must belong to the same tenant."
            )
        if credential.company_id != document.company_id:
            raise PySifenCredentialScopeError(
                "Paraguay SIFEN credential and document must belong to the same company."
            )
        if credential.material_format not in self.SUPPORTED_MATERIAL_FORMATS:
            raise PySifenCredentialConfigurationError(
                "Paraguay SIFEN credential material format is unsupported."
            )
        extracted_ruc = (credential.extracted_ruc or "").strip()
        issuer_ruc = (document.py_issuer_ruc or "").strip()
        issuer_ruc_dv = (document.py_issuer_ruc_dv or "").strip()
        if extracted_ruc and not self._ruc_matches(
            extracted_ruc,
            issuer_ruc,
            issuer_ruc_dv,
        ):
            raise PySifenCredentialScopeError(
                "Paraguay SIFEN credential RUC must match the document issuer RUC."
            )

    def _ruc_matches(self, extracted_ruc, issuer_ruc, issuer_ruc_dv):
        extracted = self.RUC_PATTERN.fullmatch(extracted_ruc)
        issuer = self.RUC_PATTERN.fullmatch(issuer_ruc)
        if not extracted or not issuer:
            return False
        if extracted.group(1) != issuer.group(1):
            return False
        extracted_dv = extracted.group(2)
        document_dv = issuer.group(2) or issuer_ruc_dv or None
        return not extracted_dv or not document_dv or extracted_dv == document_dv

    def _signing_material(self, credential):
        if credential.material_format not in self.SUPPORTED_MATERIAL_FORMATS:
            raise PySifenCredentialConfigurationError(
                "Paraguay SIFEN signing credential material format is unsupported."
            )
        try:
            material = self.provider_registry.get_provider(credential).load_material(
                credential
            )
        except Exception:
            raise PySifenCredentialMaterialError(
                "Paraguay SIFEN signing credential material could not be loaded."
            ) from None
        if not isinstance(material, dict):
            raise PySifenCredentialMaterialError(
                "Paraguay SIFEN signing credential material is invalid."
            )
        if credential.material_format == "pem_pair":
            return self._pem_material(material)
        return self._pkcs12_material(material)

    def _pem_material(self, material):
        certificate_bytes = material.get("certificate_bytes")
        private_key_bytes = material.get("private_key_bytes")
        if not isinstance(certificate_bytes, bytes) or not isinstance(
            private_key_bytes, bytes
        ):
            raise PySifenCredentialMaterialError(
                "Paraguay SIFEN signing credential material must contain certificate and private key bytes."
            )
        return certificate_bytes, private_key_bytes, self._password_bytes(
            material.get("password")
        )

    def _pkcs12_material(self, material):
        bundle_bytes = material.get("pkcs12_bytes")
        password = self._password_bytes(material.get("password"))
        if not bundle_bytes:
            raise PySifenCredentialMaterialError(
                "Paraguay SIFEN signing credential material is incomplete."
            )
        try:
            private_key, certificate, _chain = pkcs12.load_key_and_certificates(
                bundle_bytes,
                password,
            )
            if not private_key or not certificate:
                raise ValueError("incomplete PKCS#12 material")
            encryption = (
                serialization.BestAvailableEncryption(password)
                if password
                else serialization.NoEncryption()
            )
            return (
                certificate.public_bytes(serialization.Encoding.PEM),
                private_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    encryption,
                ),
                password,
            )
        except (TypeError, ValueError, UnsupportedAlgorithm):
            raise PySifenCredentialMaterialError(
                "Paraguay SIFEN PKCS#12 signing material could not be normalized."
            ) from None

    def _password_bytes(self, password):
        if password is None or isinstance(password, bytes):
            return password
        if isinstance(password, str):
            return password.encode("utf-8")
        raise PySifenCredentialMaterialError(
            "Paraguay SIFEN signing credential password is invalid."
        )

    def _csc(self, document):
        csc = document.py_csc_id
        if not csc or not csc.active:
            raise PySifenCredentialConfigurationError(
                "Active Paraguay SIFEN CSC configuration is required."
            )
        if csc.tenant_id != document.tenant_id:
            raise PySifenCredentialScopeError(
                "Paraguay SIFEN CSC and document must belong to the same tenant."
            )
        if csc.company_id != document.company_id:
            raise PySifenCredentialScopeError(
                "Paraguay SIFEN CSC and document must belong to the same company."
            )
        if csc.environment != document.environment:
            raise PySifenCredentialScopeError(
                "Paraguay SIFEN CSC and document must use the same environment."
            )
        csc_id = (csc.id_csc or "").strip()
        csc_value = (csc.csc_value or "").strip()
        if not csc_id or not csc_value:
            raise PySifenCredentialConfigurationError(
                "Paraguay SIFEN IdCSC and CSC value are required."
            )
        return csc_id, csc_value

    def _endpoint(self, adapter):
        endpoint_url = (adapter.endpoint_base_url or "").strip()
        parsed = urlparse(endpoint_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise PySifenCredentialConfigurationError(
                "Paraguay SIFEN endpoint must be an HTTPS URL."
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise PySifenCredentialConfigurationError(
                "Paraguay SIFEN endpoint must not contain credentials, query, or fragment."
            )
        return endpoint_url
