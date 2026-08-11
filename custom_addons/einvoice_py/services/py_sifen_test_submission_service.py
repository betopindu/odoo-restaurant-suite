import hashlib
import time
from dataclasses import dataclass
from urllib import error, request
from urllib.parse import urlparse

from lxml import etree

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)
from odoo.addons.einvoice_py.services.py_sifen_soap_envelope_builder import (
    PySifenSoapEnvelopeBuilder,
)
from odoo.addons.einvoice_py.services.py_xsd_validation_service import (
    PyXsdValidationService,
)


class PySifenTransportError(Exception):
    """Expected retryable transport failure raised by SIFEN transport adapters."""


class PySifenConnectionError(PySifenTransportError):
    """SIFEN transport could not establish or keep the network connection."""


class PySifenDnsError(PySifenConnectionError):
    """SIFEN transport could not resolve the sandbox host."""


class PySifenTcpError(PySifenConnectionError):
    """SIFEN transport could not open the TCP connection."""


class PySifenTimeoutError(PySifenConnectionError):
    """SIFEN transport timed out after the request may have started."""


class PySifenTlsError(PySifenTransportError):
    """SIFEN transport failed during TLS or mutual TLS negotiation."""


@dataclass(frozen=True, slots=True)
class PySifenSubmissionFailureResult:
    stage: str
    category: str
    message: str

    @property
    def ok(self):
        return False


class PySifenSubmissionService:
    """Submit final Paraguay XML to a configured SIFEN environment.

    The service keeps network transport injectable so tests never contact SIFEN
    and environment-specific endpoints can reuse the same envelope construction
    and response normalization.
    """

    SOAP_ENV_NS = "http://www.w3.org/2003/05/soap-envelope"
    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS

    DEFAULT_TIMEOUT_SECONDS = 30
    DEFAULT_ACCEPTED_CODES = {"0260"}
    DEFAULT_RETRYABLE_CODES = {"0500", "0501", "0600"}
    ALLOWED_ENVIRONMENTS = {"test", "production"}
    REQUIRED_ENVIRONMENT = None
    SERVICE_NAME = "py_sifen_submission"
    MUTUAL_TLS_TRANSPORT_ERROR = (
        "SIFEN mutual TLS submission requires an injected transport."
    )

    NS = {
        "soap": SOAP_ENV_NS,
        "sifen": SIFEN_NS,
    }

    def __init__(
        self,
        xsd_validation_service=None,
        transport=None,
        soap_envelope_builder=None,
        *,
        env=None,
        credential_provider=None,
        unsigned_xml_builder=None,
        signed_xml_preparation_service=None,
        xml_signature_service=None,
        qr_builder=None,
        rde_assembler=None,
        soap_client=None,
        response_parser=None,
        debug_logger=None,
    ):
        self.env = env
        self.xsd_validation_service = xsd_validation_service or PyXsdValidationService()
        self.transport = transport
        self.soap_envelope_builder = (
            soap_envelope_builder
            if soap_envelope_builder is not None
            else PySifenSoapEnvelopeBuilder(
                xsd_validation_service=self.xsd_validation_service
            )
        )
        self.credential_provider = credential_provider
        self.unsigned_xml_builder = unsigned_xml_builder
        self.signed_xml_preparation_service = signed_xml_preparation_service
        self.xml_signature_service = xml_signature_service
        self.qr_builder = qr_builder
        self.rde_assembler = rde_assembler
        self.soap_client = soap_client
        self.response_parser = response_parser
        self.debug_logger = debug_logger

    def submit(
        self,
        *,
        document,
        payload,
        signing_timestamp,
        credentials=None,
    ):
        """Build and submit one DE to SIFEN TEST without persistence or retry."""

        document.ensure_one()
        if (document.country_code or "").upper() != "PY":
            return self._end_to_end_failure(
                "configuration",
                "invalid_document",
                "SIFEN TEST submission requires a Paraguay document.",
            )
        if document.environment != "test":
            return self._end_to_end_failure(
                "configuration",
                "unsupported_environment",
                "SIFEN end-to-end submission requires a TEST document.",
            )
        if self.env is None:
            return self._end_to_end_failure(
                "configuration",
                "missing_environment",
                "SIFEN TEST submission requires an Odoo environment.",
            )

        if credentials is None:
            try:
                credentials = self._end_to_end_credential_provider().resolve(
                    document=document
                )
            except ValidationError:
                return self._end_to_end_failure(
                    "configuration",
                    "credential_resolution_failure",
                    "SIFEN TEST runtime credentials could not be resolved.",
                )
        else:
            from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
                PySifenRuntimeCredentials,
            )

            if not isinstance(credentials, PySifenRuntimeCredentials):
                return self._end_to_end_failure(
                    "configuration",
                    "invalid_runtime_credentials",
                    "SIFEN TEST runtime credentials are invalid.",
                )

        try:
            unsigned_xml_bytes = self._end_to_end_unsigned_builder().build_from_payload(
                payload
            )
            prepared = self._end_to_end_preparation_service().prepare(
                document,
                unsigned_xml_bytes,
                signing_timestamp,
            )
        except ValidationError:
            return self._end_to_end_failure(
                "build",
                "build_failure",
                "SIFEN TEST unsigned DE construction failed.",
            )
        self._debug("build_complete")

        try:
            signature = self._end_to_end_signature_service().sign(
                prepared_xml_bytes=prepared["prepared_xml_bytes"],
                certificate_bytes=credentials.signing_certificate_bytes,
                private_key_bytes=credentials.signing_private_key_bytes,
                private_key_password=credentials.signing_private_key_password,
                cdc=prepared["cdc"],
            )
        except ValidationError:
            return self._end_to_end_failure(
                "signing",
                "signature_failure",
                "SIFEN TEST XMLDSig generation failed.",
            )
        self._debug("signing_complete", cdc=signature.cdc)

        try:
            qr = self._end_to_end_qr_builder().build(
                signed_xml_bytes=signature.signed_xml_bytes,
                cdc=signature.cdc,
                digest_value=signature.digest_value,
                csc_id=credentials.csc_id,
                csc_secret=credentials.csc_value,
                environment=document.environment,
            )
        except ValidationError:
            return self._end_to_end_failure(
                "qr",
                "qr_failure",
                "SIFEN TEST QR construction failed.",
            )
        self._debug("qr_complete", cdc=signature.cdc)

        try:
            assembled = self._end_to_end_rde_assembler().assemble(
                signed_xml_bytes=signature.signed_xml_bytes,
                gcamfufd_xml_bytes=qr.gcamfufd_xml_bytes,
                cdc=signature.cdc,
                qr_url=qr.qr_string,
            )
        except ValidationError:
            return self._end_to_end_failure(
                "xsd_validation",
                "rde_assembly_failure",
                "SIFEN TEST final rDE assembly failed.",
            )
        if not assembled.xsd_valid:
            return self._end_to_end_failure(
                "xsd_validation",
                "xsd_validation_failure",
                "SIFEN TEST final rDE failed local XSD validation.",
            )
        self._debug(
            "xsd_validation_complete",
            cdc=signature.cdc,
            final_xml_sha256=hashlib.sha256(
                assembled.final_xml_bytes
            ).hexdigest(),
        )

        try:
            envelope = self.soap_envelope_builder.build(
                validated_rde_bytes=assembled.final_xml_bytes,
                submission_id=self._next_submission_id(document),
            )
        except ValidationError:
            return self._end_to_end_failure(
                "soap",
                "soap_generation_failure",
                "SIFEN TEST SOAP envelope generation failed.",
            )
        self._debug(
            "soap_complete",
            cdc=signature.cdc,
            request_sha256=hashlib.sha256(envelope.soap_xml_bytes).hexdigest(),
        )

        try:
            client_result = self._end_to_end_soap_client().submit(
                soap_xml_bytes=envelope.soap_xml_bytes,
                endpoint_url=credentials.endpoint_url,
                mutual_tls_credential=credentials.mutual_tls_credential,
                timeout_seconds=credentials.timeout_seconds,
            )
        except ValidationError:
            return self._end_to_end_failure(
                "soap",
                "soap_validation_failure",
                "SIFEN TEST SOAP request validation failed.",
            )
        if client_result.http_status == 0:
            self._debug("transport_failure", category=client_result.category)
            return self._end_to_end_failure(
                "transport",
                client_result.category or "transport_failure",
                client_result.error_message
                or "SIFEN TEST transport failed before receiving a response.",
            )

        parsed_response = self._end_to_end_response_parser().parse(client_result)
        self._debug(
            "response_parsed",
            classification=parsed_response.classification.value,
            http_status=parsed_response.http_status,
        )
        return parsed_response

    def _end_to_end_failure(self, stage, category, message):
        self._debug("submission_failure", stage=stage, category=category)
        return PySifenSubmissionFailureResult(
            stage=stage,
            category=category,
            message=message,
        )

    def _end_to_end_credential_provider(self):
        if self.credential_provider is None:
            from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
                PySifenCredentialProvider,
            )

            self.credential_provider = PySifenCredentialProvider(self.env)
        return self.credential_provider

    def _end_to_end_unsigned_builder(self):
        if self.unsigned_xml_builder is None:
            self.unsigned_xml_builder = PyUnsignedXmlBuilder(self.env)
        return self.unsigned_xml_builder

    def _end_to_end_preparation_service(self):
        if self.signed_xml_preparation_service is None:
            from odoo.addons.einvoice_py.services.py_signed_xml_preparation_service import (
                PySignedXmlPreparationService,
            )

            self.signed_xml_preparation_service = PySignedXmlPreparationService()
        return self.signed_xml_preparation_service

    def _end_to_end_signature_service(self):
        if self.xml_signature_service is None:
            from odoo.addons.einvoice_py.services.py_xml_signature_service import (
                PyXmlSignatureService,
            )

            self.xml_signature_service = PyXmlSignatureService()
        return self.xml_signature_service

    def _end_to_end_qr_builder(self):
        if self.qr_builder is None:
            from odoo.addons.einvoice_py.services.py_qr_generation_service import (
                PySifenQrBuilder,
            )

            self.qr_builder = PySifenQrBuilder()
        return self.qr_builder

    def _end_to_end_rde_assembler(self):
        if self.rde_assembler is None:
            from odoo.addons.einvoice_py.services.py_sifen_rde_assembler import (
                PySifenRdeAssembler,
            )

            self.rde_assembler = PySifenRdeAssembler(
                xsd_validation_service=self.xsd_validation_service
            )
        return self.rde_assembler

    def _end_to_end_soap_client(self):
        if self.soap_client is None:
            from odoo.addons.einvoice_py.services.py_sifen_soap_client import (
                PySifenSoapClient,
            )

            self.soap_client = PySifenSoapClient(
                self.env,
                xsd_validation_service=self.xsd_validation_service,
            )
        return self.soap_client

    def _end_to_end_response_parser(self):
        if self.response_parser is None:
            from odoo.addons.einvoice_py.services.py_sifen_recep_de_response_parser import (
                PySifenRecepDeResponseParser,
            )

            self.response_parser = PySifenRecepDeResponseParser()
        return self.response_parser

    def _debug(self, event, **safe_values):
        if self.debug_logger is None:
            return
        values = " ".join(
            f"{key}={value}"
            for key, value in sorted(safe_values.items())
        )
        self.debug_logger.debug(
            "SIFEN TEST submission %s%s",
            event,
            f" {values}" if values else "",
        )

    def submit_final_xml(
        self,
        *,
        document,
        final_xml_bytes,
        endpoint_url,
        soap_action=None,
        timeout_seconds=None,
        mutual_tls_credential=None,
        before_post=None,
    ):
        document.ensure_one()
        self._validate_submission_inputs(document, final_xml_bytes, endpoint_url)
        environment = document.environment
        cdc = self._extract_cdc(final_xml_bytes)
        if document.py_cdc and document.py_cdc != cdc:
            raise ValidationError("SIFEN submission CDC must match the document CDC.")

        xsd_report = self.xsd_validation_service.validate_final_signed_xml(final_xml_bytes)
        if not xsd_report.get("valid"):
            raise ValidationError(
                "Final signed Paraguay XML must pass local SIFEN XSD validation "
                "before submission."
            )

        request_xml = self.build_soap_envelope(final_xml_bytes, document=document)
        if before_post is not None:
            before_post({
                "document_id": document.id,
                "tenant_id": document.tenant_id.id,
                "company_id": document.company_id.id,
                "environment": environment,
                "cdc": cdc,
                "endpoint_url": endpoint_url,
                "request_hash": hashlib.sha256(request_xml).hexdigest(),
            })
        started = time.monotonic()
        try:
            http_response = self._transport()(
                endpoint_url=endpoint_url,
                body=request_xml,
                soap_action=soap_action,
                timeout_seconds=timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS,
                mutual_tls_credential=mutual_tls_credential,
            )
        except PySifenTransportError as error:
            return self._transport_error_result(
                endpoint_url=endpoint_url,
                request_xml=request_xml,
                error=error,
                duration_ms=self._duration_ms(started),
                cdc=cdc,
                environment=environment,
            )

        return self.normalize_response(
            endpoint_url=endpoint_url,
            request_xml=request_xml,
            response=http_response,
            duration_ms=self._duration_ms(started),
            cdc=cdc,
            environment=environment,
        )

    def build_soap_envelope(self, final_xml_bytes, *, document):
        return self.soap_envelope_builder.build(
            validated_rde_bytes=final_xml_bytes,
            submission_id=self._next_submission_id(document),
        ).soap_xml_bytes

    def _next_submission_id(self, document):
        adapter = document.adapter_config_id
        if (
            not adapter
            or adapter.tenant_id != document.tenant_id
            or adapter.company_id != document.company_id
            or adapter.environment != document.environment
        ):
            raise ValidationError(
                "SIFEN submission identifier requires matching adapter configuration."
            )
        sequence = adapter.sequence_id
        if not sequence:
            raise ValidationError(
                "SIFEN submission identifier sequence is required."
            )
        submission_id = sequence.next_by_id()
        if not submission_id or not submission_id.isdigit() or len(submission_id) > 15:
            raise ValidationError(
                "SIFEN submission identifier sequence must generate 1 to 15 digits."
            )
        return submission_id

    def normalize_response(
        self,
        *,
        endpoint_url,
        request_xml,
        response,
        duration_ms,
        cdc,
        environment="test",
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
                "environment": environment,
                "service": self.SERVICE_NAME,
                "response_category": self._response_category(status_code),
            },
        }

        if not content:
            base["authority_message"] = f"SIFEN {environment} response was empty."
            return base

        try:
            root = self._parse_xml(content)
        except etree.XMLSyntaxError:
            base["authority_message"] = f"Malformed SIFEN {environment} response."
            return base

        fault = self._soap_fault(root, environment=environment)
        if fault:
            base.update(fault)
            base["metadata_json"].update(fault.get("metadata_json") or {})
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
            raise ValidationError("SIFEN submission requires a Paraguay document.")
        if document.environment not in self.ALLOWED_ENVIRONMENTS:
            raise ValidationError("SIFEN submission requires a supported environment.")
        if self.REQUIRED_ENVIRONMENT and document.environment != self.REQUIRED_ENVIRONMENT:
            raise ValidationError(
                f"SIFEN {self.REQUIRED_ENVIRONMENT} submission requires a "
                f"{self.REQUIRED_ENVIRONMENT} environment document."
            )
        if not final_xml_bytes:
            raise ValidationError("Final signed Paraguay XML is required for SIFEN submission.")
        parsed = urlparse(endpoint_url or "")
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValidationError("SIFEN submission endpoint must be an HTTPS URL.")
        if parsed.username or parsed.password:
            raise ValidationError("SIFEN submission endpoint must not include credentials.")
        if parsed.query or parsed.fragment:
            raise ValidationError(
                "SIFEN submission endpoint must not include query strings or fragments."
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
        return self.transport or self._non_mtls_transport

    def _non_mtls_transport(
        self,
        *,
        endpoint_url,
        body,
        soap_action=None,
        timeout_seconds=None,
        mutual_tls_credential=None,
    ):
        """Development fallback for submissions without mutual TLS.

        Mutual TLS submissions must inject an appropriate transport.
        """
        if mutual_tls_credential:
            raise ValidationError(self.MUTUAL_TLS_TRANSPORT_ERROR)
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

    def _transport_error_result(
        self,
        *,
        endpoint_url,
        request_xml,
        error,
        duration_ms,
        cdc,
        environment,
    ):
        return {
            "endpoint_url": endpoint_url,
            "http_status": 0,
            "request_hash": hashlib.sha256(request_xml).hexdigest(),
            "response_hash": "",
            "duration_ms": duration_ms,
            "country_identifier": cdc,
            "authority_status_code": "",
            "authority_message": (
                f"SIFEN {environment} transport failed before a response was received."
            ),
            "authority_receipt_ref": "",
            "outcome": "failed_retryable",
            "retryable": True,
            "retry_after_seconds": 300,
            # Once the durable POST marker is committed, a transport exception
            # cannot prove that no request bytes reached the authority.
            "ambiguous": True,
            "metadata_json": {
                "environment": environment,
                "service": self.SERVICE_NAME,
                "transport_error": error.__class__.__name__,
                "transport_error_category": self._transport_error_category(error),
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

    def _soap_fault(self, root, environment="test"):
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
                "environment": environment,
                "service": self.SERVICE_NAME,
                "response_category": "soap_fault",
                "soap_fault": True,
            },
        }

    def _first_text_by_local_name(self, root, names):
        wanted = set(names)
        for node in root.iter():
            if etree.QName(node).localname in wanted:
                return (node.text or "").strip()
        return ""

    def _response_category(self, status_code):
        if status_code >= 400:
            return "http_failure"
        return "authority_response"

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

    def _transport_error_category(self, error):
        if isinstance(error, PySifenTimeoutError):
            return "timeout_failure"
        if isinstance(error, PySifenTlsError):
            return "tls_failure"
        if isinstance(error, PySifenConnectionError):
            return "connection_failure"
        return "transport_failure"


class PySifenTestSubmissionService(PySifenSubmissionService):
    """Backward-compatible SIFEN submission service restricted to test."""

    REQUIRED_ENVIRONMENT = "test"
    SERVICE_NAME = "py_sifen_test_submission"
    MUTUAL_TLS_TRANSPORT_ERROR = (
        "SIFEN sandbox mTLS submission requires PySifenSandboxTransport."
    )
