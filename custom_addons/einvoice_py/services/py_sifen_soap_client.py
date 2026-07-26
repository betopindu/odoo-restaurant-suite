import time
from dataclasses import dataclass

from lxml import etree

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_sandbox_transport import (
    PySifenSandboxTransport,
)
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenConnectionError,
    PySifenDnsError,
    PySifenTimeoutError,
    PySifenTlsError,
)
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)
from odoo.addons.einvoice_py.services.py_xsd_validation_service import (
    PyXsdValidationService,
)


@dataclass(frozen=True, slots=True)
class PySifenSoapClientResult:
    http_status: int
    response_headers: tuple
    raw_response_bytes: bytes
    parsed_xml: object | None
    elapsed_ms: int
    endpoint_url: str
    request_identifier: str
    category: str
    error_message: str


class PySifenSoapClient:
    """Send an already assembled SIFEN TEST SOAP envelope over existing mTLS."""

    SOAP_ENV_NS = "http://www.w3.org/2003/05/soap-envelope"
    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS
    XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
    CONTENT_TYPE = "application/soap+xml; charset=utf-8"
    DEFAULT_TIMEOUT_SECONDS = 30

    def __init__(
        self,
        env,
        *,
        provider_registry=None,
        transport=None,
        xsd_validation_service=None,
        clock=None,
    ):
        self.transport = (
            transport
            if transport is not None
            else PySifenSandboxTransport(
                env,
                provider_registry=provider_registry,
            )
        )
        self.xsd_validation_service = (
            xsd_validation_service
            if xsd_validation_service is not None
            else PyXsdValidationService()
        )
        self.clock = clock or time.monotonic

    def submit(
        self,
        *,
        soap_xml_bytes,
        endpoint_url,
        mutual_tls_credential,
        timeout_seconds=None,
    ):
        request_identifier = self._validate_envelope(soap_xml_bytes)
        started = self.clock()
        try:
            response = self.transport(
                endpoint_url=endpoint_url,
                body=soap_xml_bytes,
                soap_action=None,
                timeout_seconds=(
                    timeout_seconds
                    if timeout_seconds is not None
                    else self.DEFAULT_TIMEOUT_SECONDS
                ),
                mutual_tls_credential=mutual_tls_credential,
            )
        except PySifenTimeoutError:
            return self._failure(
                endpoint_url,
                request_identifier,
                started,
                "timeout",
                "SIFEN TEST request timed out.",
            )
        except PySifenDnsError:
            return self._failure(
                endpoint_url,
                request_identifier,
                started,
                "dns_failure",
                "SIFEN TEST endpoint DNS resolution failed.",
            )
        except PySifenTlsError:
            return self._failure(
                endpoint_url,
                request_identifier,
                started,
                "tls_handshake_failure",
                "SIFEN TEST TLS handshake failed.",
            )
        except PySifenConnectionError:
            return self._failure(
                endpoint_url,
                request_identifier,
                started,
                "connection_failure",
                "SIFEN TEST connection failed.",
            )
        except ValidationError:
            return self._failure(
                endpoint_url,
                request_identifier,
                started,
                "certificate_validation_failure",
                "SIFEN TEST mutual TLS credential is invalid.",
            )

        return self._response_result(
            response=response,
            endpoint_url=endpoint_url,
            request_identifier=request_identifier,
            started=started,
        )

    def _validate_envelope(self, soap_xml_bytes):
        try:
            root = self._parse(soap_xml_bytes)
        except (TypeError, ValueError, etree.XMLSyntaxError):
            raise ValidationError(
                "SIFEN TEST SOAP envelope is malformed."
            ) from None
        if root.tag != f"{{{self.SOAP_ENV_NS}}}Envelope":
            raise ValidationError(
                "SIFEN TEST SOAP 1.2 Envelope is required."
            )
        children = list(root)
        if [child.tag for child in children] != [
            f"{{{self.SOAP_ENV_NS}}}Header",
            f"{{{self.SOAP_ENV_NS}}}Body",
        ]:
            raise ValidationError(
                "SIFEN TEST SOAP envelope must contain Header and Body."
            )
        body_children = list(children[1])
        if (
            len(body_children) != 1
            or body_children[0].tag != f"{{{self.SIFEN_NS}}}rEnviDe"
        ):
            raise ValidationError(
                "SIFEN TEST SOAP Body must contain rEnviDe."
            )
        request_children = list(body_children[0])
        if [child.tag for child in request_children] != [
            f"{{{self.SIFEN_NS}}}dId",
            f"{{{self.SIFEN_NS}}}xDE",
        ]:
            raise ValidationError(
                "SIFEN TEST rEnviDe must contain dId and xDE in order."
            )
        request_identifier = (request_children[0].text or "").strip()
        if (
            not request_identifier.isdigit()
            or not 1 <= len(request_identifier) <= 15
        ):
            raise ValidationError(
                "SIFEN TEST SOAP dId must contain 1 to 15 digits."
            )
        rde_nodes = list(request_children[1])
        if (
            len(rde_nodes) != 1
            or rde_nodes[0].tag != f"{{{self.SIFEN_NS}}}rDE"
        ):
            raise ValidationError(
                "SIFEN TEST SOAP xDE must contain exactly one rDE."
            )
        if len(rde_nodes[0].findall(f"{{{self.XMLDSIG_NS}}}Signature")) != 1:
            raise ValidationError(
                "SIFEN TEST SOAP rDE must contain one XMLDSig Signature."
            )
        report = self.xsd_validation_service.validate_final_signed_xml(
            etree.tostring(rde_nodes[0], encoding="UTF-8")
        )
        if not report.get("valid"):
            raise ValidationError(
                "SIFEN TEST SOAP rDE must pass local SIFEN XSD validation."
            )
        return request_identifier

    def _response_result(
        self,
        *,
        response,
        endpoint_url,
        request_identifier,
        started,
    ):
        status = int(response.get("status_code") or 0)
        raw = response.get("content") or b""
        headers = tuple(sorted(
            (str(key), str(value))
            for key, value in (response.get("headers") or {}).items()
        ))
        parsed = None
        category = "success"
        message = ""
        if raw:
            try:
                parsed = self._parse(raw)
            except (TypeError, ValueError, etree.XMLSyntaxError):
                category = "malformed_xml_response"
                message = "SIFEN TEST returned malformed XML."
        else:
            category = "malformed_xml_response"
            message = "SIFEN TEST returned an empty response."
        if parsed is not None and parsed.find(
            f".//{{{self.SOAP_ENV_NS}}}Fault"
        ) is not None:
            category = "soap_fault"
            message = "SIFEN TEST returned a SOAP Fault."
        elif status >= 400 and category == "success":
            category = "http_error"
            message = "SIFEN TEST returned an HTTP error."
        return PySifenSoapClientResult(
            http_status=status,
            response_headers=headers,
            raw_response_bytes=raw,
            parsed_xml=parsed,
            elapsed_ms=self._elapsed_ms(started),
            endpoint_url=endpoint_url,
            request_identifier=request_identifier,
            category=category,
            error_message=message,
        )

    def _failure(
        self,
        endpoint_url,
        request_identifier,
        started,
        category,
        message,
    ):
        return PySifenSoapClientResult(
            http_status=0,
            response_headers=(),
            raw_response_bytes=b"",
            parsed_xml=None,
            elapsed_ms=self._elapsed_ms(started),
            endpoint_url=endpoint_url,
            request_identifier=request_identifier,
            category=category,
            error_message=message,
        )

    def _elapsed_ms(self, started):
        return max(0, int((self.clock() - started) * 1000))

    def _parse(self, xml_content):
        if isinstance(xml_content, str):
            xml_content = xml_content.encode("utf-8")
        parser = etree.XMLParser(
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            remove_blank_text=False,
        )
        return etree.fromstring(xml_content, parser)
