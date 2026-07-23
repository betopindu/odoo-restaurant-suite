import os
import stat
from urllib.parse import unquote, urlparse

from odoo.addons.einvoice_module.services.credential_provider import (
    FiscalCredentialMaterialProvider,
    FiscalCredentialProviderRegistry,
)


class FiscalCredentialMaterialLoadError(Exception):
    """Safe failure raised when referenced credential material cannot be loaded."""


class ExternalSecretPkcs12MaterialProvider(FiscalCredentialMaterialProvider):
    """Load transient PKCS#12 material from deployment-managed secret references."""

    provider_type = "external_secret"
    MAX_PKCS12_BYTES = 16 * 1024 * 1024
    MAX_PASSWORD_BYTES = 64 * 1024

    def load_material(self, credential):
        credential.ensure_one()
        if credential.provider_type != self.provider_type:
            raise FiscalCredentialMaterialLoadError(
                "External PKCS#12 credential provider type is invalid."
            )
        if credential.material_format != "pkcs12":
            raise FiscalCredentialMaterialLoadError(
                "External credential material must use PKCS#12 format."
            )

        pkcs12_bytes = self._read_file_reference(
            credential.secret_ref,
            max_bytes=self.MAX_PKCS12_BYTES,
            missing_message="External PKCS#12 credential material is unavailable.",
        )
        password = self._password(credential.password_secret_ref)
        return {
            "pkcs12_bytes": pkcs12_bytes,
            "password": password,
        }

    def _password(self, reference):
        if not reference:
            return None
        parsed = urlparse(reference)
        if parsed.scheme == "file":
            password = self._read_file_reference(
                reference,
                max_bytes=self.MAX_PASSWORD_BYTES,
                missing_message="External PKCS#12 credential password is unavailable.",
            )
            return password.rstrip(b"\r\n")
        if parsed.scheme == "env":
            variable_name = self._environment_variable_name(parsed)
            try:
                return os.environ[variable_name].encode("utf-8")
            except (KeyError, UnicodeEncodeError):
                raise FiscalCredentialMaterialLoadError(
                    "External PKCS#12 credential password is unavailable."
                ) from None
        raise FiscalCredentialMaterialLoadError(
            "External PKCS#12 credential password reference is unsupported."
        )

    def _read_file_reference(self, reference, *, max_bytes, missing_message):
        path = self._file_path(reference)
        try:
            with open(path, "rb") as secret_file:
                if not stat.S_ISREG(os.fstat(secret_file.fileno()).st_mode):
                    raise OSError("credential reference is not a regular file")
                value = secret_file.read(max_bytes + 1)
        except (OSError, ValueError):
            raise FiscalCredentialMaterialLoadError(missing_message) from None
        if not value or len(value) > max_bytes:
            raise FiscalCredentialMaterialLoadError(missing_message)
        return value

    def _file_path(self, reference):
        parsed = urlparse(reference or "")
        if (
            parsed.scheme != "file"
            or parsed.netloc
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise FiscalCredentialMaterialLoadError(
                "External PKCS#12 credential file reference is invalid."
            )
        path = unquote(parsed.path)
        if not path or not os.path.isabs(path):
            raise FiscalCredentialMaterialLoadError(
                "External PKCS#12 credential file reference is invalid."
            )
        return path

    def _environment_variable_name(self, parsed):
        if (
            not parsed.netloc
            or parsed.path
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise FiscalCredentialMaterialLoadError(
                "External PKCS#12 credential password reference is invalid."
            )
        name = parsed.netloc
        if not name or not name.replace("_", "").isalnum():
            raise FiscalCredentialMaterialLoadError(
                "External PKCS#12 credential password reference is invalid."
            )
        return name


FiscalCredentialProviderRegistry.register(ExternalSecretPkcs12MaterialProvider)
