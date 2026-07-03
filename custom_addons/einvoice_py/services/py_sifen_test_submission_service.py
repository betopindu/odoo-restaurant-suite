import hashlib
import time
from urllib import error, request
from urllib.parse import urlparse

from lxml import etree

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)
from odoo.addons.einvoice_py.services.py_xsd_validation_service import (
    PyXsdValidationService,
)


class PySifenTransportError(Exception):
    """Expected retryable transport failure raised by SIFEN transport adapters."""


class PySifenTestSubmissionService:
    """Submit final Paraguay XML to a SIFEN test endpoint.

    The service keeps network transport injectable so tests never contact SIFEN
    and future production transport can add mTLS/retry policy without changing
    envelope construction or response normalization.
    """

    SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS

    DEFAULT_TIMEOUT_SECONDS = 30
    DEFAULT_ACCEPTED_CODES = {"0300"}
    DEFAULT_RETRYABLE_CODES = {"0500", "0501", "0600"}

    NS = {
        "soap": SOAP_ENV_NS,
        "sifen": SIFEN_NS,
    }

    def __init__(self, xsd_validation_service=None, transport=None):
        self.xsd_validation_service = xsd_validation_service or PyXsdValidationService()
        self.transport = transport

    def submit_final_xml(
        self,
        *,
        document,
        final_xml_bytes,
        endpoint_url,
        soap_action=None,
        timeout_seconds=None,
    ):
        document.ensure_one()
        self._validate_submission_inputs(document, final_xml_bytes, endpoint_url)
        cdc = self._extract_cdc(final_xml_bytes)
        if document.py_cdc and document.py_cdc != cdc:
            raise ValidationError("SIFEN test submission CDC must match the document CDC.")

        xsd_report = self.xsd_validation_service.validate_final_signed_xml(final_xml_bytes)
        if not xsd_report.get("valid"):
            raise ValidationError(
                "Final signed Paraguay XML must pass local SIFEN XSD validation "
                "before test submission."
            )

        request_xml = self.build_soap_envelope(final_xml_bytes)
        started = time.monotonic()
        try:
            http_response = self._transport()(
                endpoint_url=endpoint_url,
                body=request_xml,
                soap_action=soap_action,
                timeout_seconds=timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS,
            )
        except PySifenTransportError as error:
            return self._transport_error_result(
                endpoint_url=endpoint_url,
                request_xml=request_xml,
                error=error,
                duration_ms=self._duration_ms(started),
                cdc=cdc,
            )

        return self.normalize_response(
            endpoint_url=endpoint_url,
            request_xml=request_xml,
            response=http_response,
            duration_ms=self._duration_ms(started),
            cdc=cdc,
        )

    def build_soap_envelope(self, final_xml_bytes):
        try:
            de_node = self._parse_xml(final_xml_bytes)
        except etree.XMLSyntaxError as error:
            raise ValidationError(f"Malformed final Paraguay XML: {error}") from error

        envelope = etree.Element(f"{{{self.SOAP_ENV_NS}}}Envelope", nsmap={
            "soapenv": self.SOAP_ENV_NS,
            "sifen": self.SIFEN_NS,
        })
        body = etree.SubElement(envelope, f"{{{self.SOAP_ENV_NS}}}Body")
        request_node = etree.SubElement(body, f"{{{self.SIFEN_NS}}}rEnviDE")
        request_node.append(de_node)
        etree.indent(envelope, space="  ")
        return etree.tostring(envelope, encoding="UTF-8", xml_declaration=True)

    def normalize_response(
        self,
        *,
        endpoint_url,
        request_xml,
        response,
        duration_ms,
        cdc,
    ):
        status_code = self._response_status_code(response)
        content = self._response_content(response)
        base = {
            "endpoint_url": endpoint_url,
            "http_status": status_code,
            "request_hash": hashlib.sha256(request_xml).hexdigest(),
            "response_hash": hashlib.sha256(content).hexdigest() if content else "",
            "duration_ms": duration_ms,
            "country_identifier": cdc,
            "authority_status_code": "",
            "authority_message": "",
            "authority_receipt_ref": "",
            "outcome": "failed_retryable" if status_code >= 500 else "failed_final",
            "retryable": status_code >= 500,
            "retry_after_seconds": 300 if status_code >= 500 else 0,
            "metadata_json": {
                "environment": "test",
                "service": "py_sifen_test_submission",
            },
        }

        if not content:
            base["authority_message"] = "SIFEN test response was empty."
            return base

        try:
            root = self._parse_xml(content)
        except etree.XMLSyntaxError:
            base["authority_message"] = "Malformed SIFEN test response."
            return base

        fault = self._soap_fault(root)
        if fault:
            base.update(fault)
            return base

        authority_code = self._first_text_by_local_name(root, [
            "dCodRes",
            "codigo",
            "codRes",
            "statusCode",
        ])
        authority_message = self._first_text_by_local_name(root, [
            "dMsgRes",
            "mensaje",
            "msgRes",
            "statusMessage",
        ])
        receipt_ref = self._first_text_by_local_name(root, [
            "dProtAut",
            "protocolo",
            "nroProtocolo",
            "receipt",
        ])

        base.update({
            "authority_status_code": authority_code,
            "authority_message": authority_message,
            "authority_receipt_ref": receipt_ref,
        })
        base.update(self._outcome_from_authority_code(authority_code, status_code))
        return base

    def _validate_submission_inputs(self, document, final_xml_bytes, endpoint_url):
        if (document.country_code or "").upper() != "PY":
            raise ValidationError("SIFEN test submission requires a Paraguay document.")
        if document.environment != "test":
            raise ValidationError("SIFEN test submission requires a test environment document.")
        if not final_xml_bytes:
            raise ValidationError("Final signed Paraguay XML is required for SIFEN test submission.")
        parsed = urlparse(endpoint_url or "")
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValidationError("SIFEN test submission endpoint must be an HTTPS URL.")
        if parsed.username or parsed.password:
            raise ValidationError("SIFEN test submission endpoint must not include credentials.")
        if parsed.query or parsed.fragment:
            raise ValidationError(
                "SIFEN test submission endpoint must not include query strings or fragments."
            )

    def _extract_cdc(self, xml_content):
        try:
            root = self._parse_xml(xml_content)
        except etree.XMLSyntaxError as error:
            raise ValidationError(f"Malformed final Paraguay XML: {error}") from error
        de_nodes = root.findall(f"{{{self.SIFEN_NS}}}DE")
        if len(de_nodes) != 1:
            raise ValidationError("Final signed Paraguay XML must contain exactly one DE.")
        cdc = (de_nodes[0].get("Id") or "").strip()
        if not cdc:
            raise ValidationError("Final signed Paraguay XML DE Id CDC is required.")
        return cdc

    def _parse_xml(self, xml_content):
        if isinstance(xml_content, str):
            xml_content = xml_content.encode("utf-8")
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
        return etree.fromstring(xml_content, parser)

    def _transport(self):
        return self.transport or self._urllib_transport

    def _urllib_transport(self, *, endpoint_url, body, soap_action=None, timeout_seconds=None):
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
            with request.urlopen(
                http_request,
                timeout=timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS,
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
        except (error.URLError, TimeoutError, OSError) as transport_error:
            raise PySifenTransportError() from transport_error

    def _transport_error_result(self, *, endpoint_url, request_xml, error, duration_ms, cdc):
        return {
            "endpoint_url": endpoint_url,
            "http_status": 0,
            "request_hash": hashlib.sha256(request_xml).hexdigest(),
            "response_hash": "",
            "duration_ms": duration_ms,
            "country_identifier": cdc,
            "authority_status_code": "",
            "authority_message": "SIFEN test transport failed before a response was received.",
            "authority_receipt_ref": "",
            "outcome": "failed_retryable",
            "retryable": True,
            "retry_after_seconds": 300,
            "metadata_json": {
                "environment": "test",
                "service": "py_sifen_test_submission",
                "transport_error": error.__class__.__name__,
                "transport_error_category": "retryable_transport",
            },
        }

    def _response_status_code(self, response):
        if isinstance(response, dict):
            return int(response.get("status_code") or response.get("http_status") or 0)
        return int(getattr(response, "status_code", None) or getattr(response, "code", None) or 0)

    def _response_content(self, response):
        if isinstance(response, dict):
            content = response.get("content") or response.get("body") or b""
        else:
            content = getattr(response, "content", None) or getattr(response, "body", None) or b""
        if isinstance(content, str):
            return content.encode("utf-8")
        return content

    def _soap_fault(self, root):
        fault = root.find(".//soap:Fault", namespaces=self.NS)
        if fault is None:
            return {}
        code = self._first_text_by_local_name(fault, ["faultcode"]) or "SOAPFault"
        message = self._first_text_by_local_name(fault, ["faultstring"]) or "SIFEN SOAP fault."
        return {
            "authority_status_code": code,
            "authority_message": message,
            "outcome": "failed_retryable",
            "retryable": True,
            "retry_after_seconds": 300,
            "metadata_json": {
                "environment": "test",
                "service": "py_sifen_test_submission",
                "soap_fault": True,
            },
        }

    def _first_text_by_local_name(self, root, names):
        wanted = set(names)
        for node in root.iter():
            if etree.QName(node).localname in wanted:
                return (node.text or "").strip()
        return ""

    def _outcome_from_authority_code(self, authority_code, http_status):
        if authority_code in self.DEFAULT_ACCEPTED_CODES:
            return {
                "outcome": "accepted",
                "retryable": False,
                "retry_after_seconds": 0,
            }
        if authority_code in self.DEFAULT_RETRYABLE_CODES or http_status >= 500:
            return {
                "outcome": "failed_retryable",
                "retryable": True,
                "retry_after_seconds": 300,
            }
        return {
            "outcome": "rejected" if authority_code else "failed_final",
            "retryable": False,
            "retry_after_seconds": 0,
        }

    def _duration_ms(self, started):
        return int((time.monotonic() - started) * 1000)
