import socket
import ssl
import tempfile
from urllib.parse import urlparse
from urllib import error, request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_module.services.credential_provider import (
    FiscalCredentialProviderRegistry,
)
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenConnectionError,
    PySifenTlsError,
)


class PySifenSandboxTransport:
    """HTTPS SOAP transport for the SIFEN test environment with mTLS support."""

    def __init__(self, env, provider_registry=None, urlopen=None):
        self.env = env
        self.provider_registry = provider_registry or FiscalCredentialProviderRegistry(env)
        self.urlopen = urlopen or request.urlopen

    def __call__(
        self,
        *,
        endpoint_url,
        body,
        soap_action=None,
        timeout_seconds=None,
        mutual_tls_credential=None,
    ):
        self._validate_endpoint_url(endpoint_url)
        if not mutual_tls_credential:
            raise ValidationError("SIFEN sandbox transport requires a mutual TLS credential.")
        mutual_tls_credential.ensure_one()
        if mutual_tls_credential.material_format not in ("pkcs12", "pem_pair"):
            raise ValidationError(
                "SIFEN sandbox transport supports PKCS#12 or PEM pair mutual TLS credentials."
            )

        material = self.provider_registry.get_provider(
            mutual_tls_credential
        ).load_material(mutual_tls_credential)
        context = self._ssl_context_from_material(mutual_tls_credential, material)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "Accept": "text/xml, application/xml",
        }
        if soap_action:
            headers["SOAPAction"] = soap_action
        http_request = request.Request(
            endpoint_url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with self.urlopen(
                http_request,
                timeout=timeout_seconds,
                context=context,
            ) as response:
                return {
                    "status_code": response.getcode(),
                    "content": response.read(),
                    "headers": dict(response.headers.items()),
                }
        except error.HTTPError as http_error:
            return {
                "status_code": http_error.code,
                "content": http_error.read(),
                "headers": dict(http_error.headers.items()) if http_error.headers else {},
            }
        except error.URLError as transport_error:
            if isinstance(getattr(transport_error, "reason", None), ssl.SSLError):
                raise PySifenTlsError() from transport_error
            raise PySifenConnectionError() from transport_error
        except ssl.SSLError as transport_error:
            raise PySifenTlsError() from transport_error
        except (TimeoutError, socket.timeout, OSError) as transport_error:
            raise PySifenConnectionError() from transport_error

    def _validate_endpoint_url(self, endpoint_url):
        parsed = urlparse(endpoint_url or "")
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValidationError("SIFEN sandbox endpoint must be an HTTPS URL.")
        if parsed.username or parsed.password:
            raise ValidationError("SIFEN sandbox endpoint must not include credentials.")
        if parsed.query or parsed.fragment:
            raise ValidationError(
                "SIFEN sandbox endpoint must not include query strings or fragments."
            )

    def _ssl_context_from_material(self, credential, material):
        if not isinstance(material, dict):
            raise ValidationError("SIFEN sandbox credential material must be a dictionary.")
        if credential.material_format == "pkcs12":
            cert_bytes, key_bytes = self._pem_pair_from_pkcs12(material)
        else:
            cert_bytes = material.get("certificate_bytes")
            key_bytes = material.get("private_key_bytes")
        if not cert_bytes or not key_bytes:
            raise ValidationError(
                "SIFEN sandbox mutual TLS credential material is incomplete."
            )

        return self._ssl_context_from_pem_pair(cert_bytes=cert_bytes, key_bytes=key_bytes)

    def _ssl_context_from_pem_pair(self, *, cert_bytes, key_bytes):
        """Create an SSL context from transient PEM bytes.

        Python's stdlib ssl API requires filesystem paths for load_cert_chain.
        These files are OS-managed temporary files created with mode 0600 and
        are unlinked when the context is built. Paths and secret bytes are never
        returned, logged, or stored in Odoo records.
        """
        context = ssl.create_default_context()
        with tempfile.NamedTemporaryFile(mode="w+b") as cert_file, tempfile.NamedTemporaryFile(
            mode="w+b"
        ) as key_file:
            cert_file.write(cert_bytes)
            cert_file.flush()
            key_file.write(key_bytes)
            key_file.flush()
            try:
                context.load_cert_chain(certfile=cert_file.name, keyfile=key_file.name)
            except ssl.SSLError as error:
                raise PySifenTlsError() from error
        return context

    def _pem_pair_from_pkcs12(self, material):
        bundle_bytes = material.get("pkcs12_bytes")
        if not bundle_bytes:
            raise ValidationError(
                "SIFEN sandbox PKCS#12 mutual TLS credential material is incomplete."
            )
        password = material.get("password")
        if isinstance(password, str):
            password = password.encode("utf-8")
        try:
            private_key, certificate, _chain = pkcs12.load_key_and_certificates(
                bundle_bytes,
                password,
            )
        except (TypeError, ValueError) as error:
            raise PySifenTlsError() from error
        if not private_key or not certificate:
            raise ValidationError(
                "SIFEN sandbox PKCS#12 mutual TLS credential must contain a certificate and key."
            )
        return (
            certificate.public_bytes(serialization.Encoding.PEM),
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
