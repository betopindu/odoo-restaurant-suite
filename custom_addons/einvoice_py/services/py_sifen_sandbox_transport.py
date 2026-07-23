import json
import socket
import ssl
import tempfile
from urllib.parse import urlparse
from urllib import error, request

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from odoo import fields
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_module.services.credential_provider import (
    FiscalCredentialProviderRegistry,
)
from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
    PySifenCredentialConfigurationError,
    PySifenCredentialMaterialError,
    PySifenCredentialProvider,
)
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenConnectionError,
    PySifenDnsError,
    PySifenTcpError,
    PySifenTlsError,
)


class PySifenSandboxTransport:
    """HTTPS SOAP transport for the SIFEN test environment with mTLS support."""

    DEFAULT_VERIFY_TIMEOUT_SECONDS = 10

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
        context = self._ssl_context_from_credential(mutual_tls_credential)
        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8",
            "Accept": "application/soap+xml, application/xml",
        }
        if soap_action:
            headers["Content-Type"] += f'; action="{soap_action}"'
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
            raise self._connection_error_from_reason(
                getattr(transport_error, "reason", None)
            ) from transport_error
        except ssl.SSLError as transport_error:
            raise PySifenTlsError() from transport_error
        except socket.gaierror as transport_error:
            raise PySifenDnsError() from transport_error
        except (ConnectionRefusedError, TimeoutError, socket.timeout) as transport_error:
            raise PySifenTcpError() from transport_error
        except OSError as transport_error:
            raise PySifenConnectionError() from transport_error

    def verify_connection(
        self,
        *,
        endpoint_url,
        timeout_seconds=None,
        mutual_tls_credential=None,
    ):
        """Verify sandbox mTLS connectivity without submitting a DE payload.

        The probe performs an HTTPS HEAD request with the same SSL context used
        by submission. An HTTP error still proves that DNS, TCP, and TLS reached
        the remote authority; business response handling remains outside this
        connectivity check. The default timeout is intentionally short because
        this is a connectivity probe, not a document submission.
        """
        timeout_seconds = timeout_seconds or self.DEFAULT_VERIFY_TIMEOUT_SECONDS
        if not mutual_tls_credential:
            return self._verification_result(
                category="credential_absent",
                status_code=0,
                tls_handshake_succeeded=False,
            )
        try:
            self._validate_endpoint_url(endpoint_url)
            context = self._ssl_context_from_credential(mutual_tls_credential)
            http_request = request.Request(
                endpoint_url,
                headers={"Accept": "*/*"},
                method="HEAD",
            )
            with self.urlopen(
                http_request,
                timeout=timeout_seconds,
                context=context,
            ) as response:
                return self._verification_result(
                    category="endpoint_reachable",
                    status_code=response.getcode(),
                    tls_handshake_succeeded=True,
                )
        except error.HTTPError as http_error:
            return self._verification_result(
                category="http_response_received",
                status_code=http_error.code,
                tls_handshake_succeeded=True,
            )
        except error.URLError as transport_error:
            return self._verification_failure_from_reason(
                getattr(transport_error, "reason", None)
            )
        except ssl.SSLError as transport_error:
            return self._verification_failure_from_reason(transport_error)
        except PySifenTlsError:
            return self._verification_result(
                category="credential_invalid",
                status_code=0,
                tls_handshake_succeeded=False,
            )
        except socket.gaierror:
            return self._verification_failure_result(PySifenDnsError())
        except (ConnectionRefusedError, TimeoutError, socket.timeout):
            return self._verification_failure_result(PySifenTcpError())
        except ValidationError:
            return self._verification_result(
                category="configuration_invalid",
                status_code=0,
                tls_handshake_succeeded=False,
            )
        except OSError:
            return self._verification_failure_result(PySifenConnectionError())

    def verify_document_connection(self, document, credential_provider=None):
        """Verify a Paraguay TEST document's configured sandbox connection."""
        document.ensure_one()
        if (document.country_code or "").upper() != "PY":
            return self._persist_document_verification(
                document,
                self._verification_result(
                    category="configuration_invalid",
                    status_code=0,
                    tls_handshake_succeeded=False,
                ),
            )
        if document.environment != "test":
            return self._persist_document_verification(
                document,
                self._verification_result(
                    category="configuration_invalid",
                    status_code=0,
                    tls_handshake_succeeded=False,
                ),
            )
        installation_failure = self._installation_failure_result(document)
        if installation_failure:
            return self._persist_document_verification(
                document,
                installation_failure,
            )
        provider = (
            credential_provider
            if credential_provider is not None
            else PySifenCredentialProvider(
                self.env,
                provider_registry=self.provider_registry,
            )
        )
        try:
            credentials = provider.resolve(document=document)
        except PySifenCredentialConfigurationError:
            result = self._verification_result(
                category="configuration_invalid",
                status_code=0,
                tls_handshake_succeeded=False,
            )
            return self._persist_document_verification(document, result)
        except PySifenCredentialMaterialError:
            result = self._verification_result(
                category="credential_invalid",
                status_code=0,
                tls_handshake_succeeded=False,
            )
            return self._persist_document_verification(document, result)
        except Exception:
            result = self._verification_result(
                category="configuration_invalid",
                status_code=0,
                tls_handshake_succeeded=False,
            )
            return self._persist_document_verification(document, result)
        try:
            result = self.verify_connection(
                endpoint_url=credentials.endpoint_url,
                timeout_seconds=credentials.timeout_seconds,
                mutual_tls_credential=credentials.mutual_tls_credential,
            )
        except Exception:
            result = self._verification_result(
                category="configuration_invalid",
                status_code=0,
                tls_handshake_succeeded=False,
            )
        return self._persist_document_verification(document, result)

    def _installation_failure_result(self, document):
        adapter = document.adapter_config_id
        if not adapter:
            return None
        bindings = adapter.credential_binding_ids.filtered(
            lambda binding: (
                binding.role == "mutual_tls"
                and binding.credential_id.active
            )
        )
        if len(bindings) != 1:
            return self._verification_result(
                category="credential_absent",
                status_code=0,
                tls_handshake_succeeded=False,
            )
        credential = bindings.credential_id
        if (
            credential.not_after
            and credential.not_after < fields.Datetime.now()
        ):
            return self._verification_result(
                category="certificate_expired",
                status_code=0,
                tls_handshake_succeeded=False,
            )
        if credential.inspection_status == "pending":
            return None
        try:
            inspection_report = json.loads(
                credential.inspection_report_json or "{}"
            )
        except (TypeError, ValueError):
            return self._verification_result(
                category="configuration_invalid",
                status_code=0,
                tls_handshake_succeeded=False,
            )
        errors = " ".join(inspection_report.get("errors") or [])
        if "expired at the inspection time" in errors:
            category = "certificate_expired"
        elif "could not be parsed or decrypted" in errors:
            category = "credential_password_invalid"
        elif credential.inspection_status != "valid":
            category = "credential_invalid"
        else:
            return None
        return self._verification_result(
            category=category,
            status_code=0,
            tls_handshake_succeeded=False,
        )

    def _persist_document_verification(self, document, result):
        adapter = document.adapter_config_id
        if not adapter:
            return result
        try:
            metadata = json.loads(adapter.metadata_json or "{}")
        except (TypeError, ValueError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["sifen_test_mtls_preflight"] = {
            "ok": bool(result.get("ok")),
            "category": result.get("category", "configuration_invalid"),
            "http_status": int(result.get("http_status") or 0),
            "client_certificate_configured": bool(
                result.get("client_certificate_configured")
            ),
            "server_certificate_verified": bool(
                result.get("server_certificate_verified")
            ),
            "tls_handshake_succeeded": bool(
                result.get("tls_handshake_succeeded")
            ),
            "checked_at": fields.Datetime.to_string(fields.Datetime.now()),
        }
        adapter.metadata_json = json.dumps(metadata, sort_keys=True)
        return result

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

    def _ssl_context_from_credential(self, mutual_tls_credential):
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
        return self._ssl_context_from_material(mutual_tls_credential, material)

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

    def _connection_error_from_reason(self, reason):
        if isinstance(reason, ssl.SSLError):
            return PySifenTlsError()
        if isinstance(reason, socket.gaierror):
            return PySifenDnsError()
        if isinstance(reason, (ConnectionRefusedError, TimeoutError, socket.timeout)):
            return PySifenTcpError()
        if isinstance(reason, OSError):
            return PySifenConnectionError()
        return PySifenConnectionError()

    def _verification_failure_result(self, error):
        category = "connection_failure"
        if isinstance(error, PySifenDnsError):
            category = "dns_failure"
        elif isinstance(error, PySifenTcpError):
            category = "tcp_failure"
        elif isinstance(error, PySifenTlsError):
            category = "tls_failure"
        return self._verification_result(
            category=category,
            status_code=0,
            tls_handshake_succeeded=False,
            error_class=error.__class__.__name__,
        )

    def _verification_failure_from_reason(self, reason):
        if isinstance(reason, ssl.SSLCertVerificationError):
            return self._verification_result(
                category="server_certificate_untrusted",
                status_code=0,
                tls_handshake_succeeded=False,
            )
        if isinstance(reason, ssl.SSLError) and self._is_client_rejection(reason):
            return self._verification_result(
                category="client_certificate_rejected",
                status_code=0,
                tls_handshake_succeeded=False,
            )
        return self._verification_failure_result(
            self._connection_error_from_reason(reason)
        )

    def _is_client_rejection(self, error):
        reason = str(getattr(error, "reason", "") or "").upper()
        return reason in {
            "CERTIFICATE_REQUIRED",
            "SSLV3_ALERT_BAD_CERTIFICATE",
            "SSLV3_ALERT_CERTIFICATE_EXPIRED",
            "TLSV1_ALERT_ACCESS_DENIED",
            "TLSV1_ALERT_UNKNOWN_CA",
        }

    def _verification_result(
        self,
        *,
        category,
        status_code,
        tls_handshake_succeeded,
        error_class="",
    ):
        return {
            "ok": category in {
                "endpoint_reachable",
                "http_response_received",
            },
            "category": category,
            "http_status": int(status_code or 0),
            "tls_handshake_succeeded": bool(tls_handshake_succeeded),
            "client_certificate_configured": category in {
                "dns_failure",
                "tcp_failure",
                "tls_failure",
                "client_certificate_rejected",
                "server_certificate_untrusted",
                "connection_failure",
                "endpoint_reachable",
                "http_response_received",
            },
            "server_certificate_verified": category in {
                "endpoint_reachable",
                "http_response_received",
            },
            "error_class": error_class,
            "message": self._verification_message(category),
        }

    def _verification_message(self, category):
        messages = {
            "endpoint_reachable": "SIFEN TEST endpoint is reachable.",
            "http_response_received": "SIFEN TEST endpoint returned an HTTP response.",
            "configuration_invalid": "SIFEN TEST preflight configuration is invalid.",
            "credential_absent": "SIFEN TEST mutual TLS credential is absent.",
            "credential_invalid": "SIFEN TEST mutual TLS credential is invalid.",
            "credential_password_invalid": "SIFEN TEST PKCS#12 password is invalid.",
            "certificate_expired": "SIFEN TEST client certificate is expired.",
            "dns_failure": "SIFEN sandbox host could not be resolved.",
            "tcp_failure": "SIFEN sandbox TCP connection failed.",
            "tls_failure": "SIFEN sandbox TLS handshake failed.",
            "client_certificate_rejected": "SIFEN TEST rejected the client certificate.",
            "server_certificate_untrusted": "SIFEN TEST server certificate is not trusted.",
            "connection_failure": "SIFEN sandbox connection failed.",
        }
        return messages.get(category, "SIFEN sandbox connection check failed.")
