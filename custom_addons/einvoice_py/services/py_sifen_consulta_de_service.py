import hashlib
import json
import re
import time
from urllib.parse import urlsplit, urlunsplit

from lxml import etree

from odoo import fields
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
    PySifenCredentialProvider,
    PySifenRuntimeCredentials,
)
from odoo.addons.einvoice_py.services.py_sifen_sandbox_transport import (
    PySifenSandboxTransport,
)
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import (
    PySifenTransportError,
)
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)


class PySifenDocumentQueryService:
    """Query an approved SIFEN TEST DTE by CDC and persist a safe audit record."""

    SOAP_ENV_NS = "http://www.w3.org/2003/05/soap-envelope"
    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS
    TEST_ENDPOINT_URL = (
        "https://sifen-test.set.gov.py/de/ws/consultas/consulta.wsdl"
    )
    _XML_DECLARATION_RE = re.compile(
        r"\A<\?xml[ \t\r\n]+version[ \t\r\n]*=[ \t\r\n]*"
        r"(?P<version_quote>['\"])(?:1\.0|1\.1)(?P=version_quote)"
        r"(?:[ \t\r\n]+encoding[ \t\r\n]*=[ \t\r\n]*"
        r"(?P<encoding_quote>['\"])(?P<encoding>[A-Za-z][A-Za-z0-9._-]*)"
        r"(?P=encoding_quote))?"
        r"(?:[ \t\r\n]+standalone[ \t\r\n]*=[ \t\r\n]*"
        r"(?P<standalone_quote>['\"])(?P<standalone>yes|no)"
        r"(?P=standalone_quote))?[ \t\r\n]*\?>\Z"
    )

    def __init__(
        self,
        env,
        *,
        credential_provider=None,
        transport=None,
        endpoint_url=None,
    ):
        self.env = env
        self.credential_provider = (
            credential_provider
            if credential_provider is not None
            else PySifenCredentialProvider(env)
        )
        self.transport = (
            transport
            if transport is not None
            else PySifenSandboxTransport(env)
        )
        self.endpoint_url = endpoint_url or self.TEST_ENDPOINT_URL

    def query(self, *, document, cdc=None, credentials=None):
        document.ensure_one()
        self._validate_document(document)
        cdc = self._cdc(document, cdc)
        started_at = fields.Datetime.now()
        started_monotonic = time.monotonic()
        transmission = self._create_transmission(
            document=document,
            cdc=cdc,
            started_at=started_at,
        )
        request_hash = ""
        try:
            runtime_credentials = (
                credentials
                if credentials is not None
                else self.credential_provider.resolve(document=document)
            )
            if not isinstance(runtime_credentials, PySifenRuntimeCredentials):
                raise ValidationError(
                    "SIFEN Consulta DE runtime credentials are invalid."
                )
            request_xml = self.build_request(document=document, cdc=cdc)
            request_hash = hashlib.sha256(request_xml).hexdigest()
            response = self.transport(
                endpoint_url=self.endpoint_url,
                body=request_xml,
                timeout_seconds=runtime_credentials.timeout_seconds,
                mutual_tls_credential=runtime_credentials.mutual_tls_credential,
            )
            result = self.normalize_response(
                response=response,
                request_hash=request_hash,
                expected_cdc=cdc,
            )
        except PySifenTransportError:
            result = self._failure_result(
                category="transport_failure",
                message="SIFEN Consulta DE did not return a response.",
                retryable=True,
            )
        except ValidationError:
            result = self._failure_result(
                category="configuration_invalid",
                message="SIFEN Consulta DE configuration is invalid.",
                retryable=False,
            )
        except Exception:
            result = self._failure_result(
                category="consulta_failure",
                message="SIFEN Consulta DE could not be completed.",
                retryable=False,
            )
        if request_hash and not result.get("request_hash"):
            result["request_hash"] = request_hash
        result["duration_ms"] = max(
            0, int((time.monotonic() - started_monotonic) * 1000)
        )
        result["endpoint_url"] = self._safe_endpoint(self.endpoint_url)
        self._finish_transmission(
            transmission=transmission,
            result=result,
            finished_at=fields.Datetime.now(),
        )
        result["transmission_id"] = transmission.id
        return result

    def build_request(self, *, document, cdc):
        envelope = etree.Element(
            f"{{{self.SOAP_ENV_NS}}}Envelope",
            nsmap={
                "soap": self.SOAP_ENV_NS,
                "sifen": self.SIFEN_NS,
            },
        )
        body = etree.SubElement(
            envelope,
            f"{{{self.SOAP_ENV_NS}}}Body",
        )
        request_node = etree.SubElement(
            body,
            f"{{{self.SIFEN_NS}}}rEnviConsDeRequest",
        )
        etree.SubElement(
            request_node,
            f"{{{self.SIFEN_NS}}}dId",
        ).text = self._next_query_id(document)
        etree.SubElement(
            request_node,
            f"{{{self.SIFEN_NS}}}dCDC",
        ).text = cdc
        etree.indent(envelope, space="  ")
        return etree.tostring(
            envelope,
            encoding="UTF-8",
            xml_declaration=True,
        )

    def normalize_response(self, *, response, request_hash, expected_cdc):
        status_code = self._response_status_code(response)
        content = self._response_content(response)
        response_hash = hashlib.sha256(content).hexdigest() if content else ""
        base = {
            "ok": False,
            "category": "malformed_response",
            "http_status": status_code,
            "request_hash": request_hash,
            "response_hash": response_hash,
            "authority_code": "",
            "authority_message": "",
            "authority_receipt_ref": "",
            "approved": False,
            "not_approved": False,
            "retryable": False,
            "authority_timestamp": "",
        }
        if not content:
            base["authority_message"] = "SIFEN Consulta DE response was empty."
            return base
        try:
            root = self._parse_xml(content)
        except (TypeError, ValueError, etree.XMLSyntaxError):
            base["authority_message"] = "SIFEN Consulta DE response was malformed."
            return base

        fault = root.find(
            f".//{{{self.SOAP_ENV_NS}}}Fault",
        )
        if fault is not None:
            base.update({
                "category": "soap_fault",
                "authority_code": "SOAPFault",
                "authority_message": "SIFEN Consulta DE returned a SOAP Fault.",
                "retryable": True,
            })
            return base

        response_node = root.find(
            f".//{{{self.SIFEN_NS}}}rEnviConsDeResponse",
        )
        if response_node is None:
            base["authority_message"] = "SIFEN Consulta DE response was malformed."
            return base
        authority_code = self._direct_text(response_node, "dCodRes")
        authority_message = self._direct_text(response_node, "dMsgRes")
        receipt_ref = self._direct_text(response_node, "dProtAut")
        authority_timestamp = self._direct_text(response_node, "dFecProc")
        base.update({
            "authority_code": authority_code,
            "authority_message": authority_message,
            "authority_receipt_ref": receipt_ref,
            "authority_timestamp": authority_timestamp,
        })
        if status_code < 200 or status_code >= 300:
            base.update({
                "category": "http_failure",
                "retryable": status_code >= 500,
            })
            return base
        if authority_code == "0420":
            base.update({
                "ok": True,
                "category": "not_approved",
                "not_approved": True,
            })
            return base
        if authority_code != "0422":
            base.update({
                "category": "unsupported_response",
                "retryable": status_code >= 500,
            })
            return base

        returned_content = self._returned_content(response_node)
        base["response_structure"] = returned_content[1]
        if returned_content[0] is None:
            base.update({
                "category": "malformed_response",
                "authority_message": (
                    "SIFEN Consulta DE did not return a valid DE container."
                ),
            })
            return base
        returned_cdc, returned_protocol = returned_content[0]
        if returned_protocol:
            base["authority_receipt_ref"] = returned_protocol
        if returned_cdc != expected_cdc:
            base.update({
                "category": "cdc_mismatch",
                "authority_message": (
                    "SIFEN Consulta DE returned content for a different CDC."
                ),
            })
            return base
        base.update({
            "ok": True,
            "category": "approved",
            "approved": True,
        })
        return base

    def _validate_document(self, document):
        if (document.country_code or "").upper() != "PY":
            raise ValidationError(
                "SIFEN Consulta DE requires a Paraguay document."
            )
        if document.environment != "test":
            raise ValidationError(
                "SIFEN Consulta DE supports TEST documents only."
            )

    def _cdc(self, document, supplied_cdc):
        cdc = (
            supplied_cdc
            or document.country_identifier
            or document.py_cdc
            or ""
        ).strip()
        if not cdc.isdigit() or len(cdc) != 44:
            raise ValidationError(
                "SIFEN Consulta DE requires a 44-digit CDC."
            )
        document_cdc = (
            document.country_identifier or document.py_cdc or ""
        ).strip()
        if document_cdc and document_cdc != cdc:
            raise ValidationError(
                "SIFEN Consulta DE CDC must match the document CDC."
            )
        return cdc

    def _next_query_id(self, document):
        adapter = document.adapter_config_id
        if (
            not adapter
            or not adapter.active
            or (adapter.country_code or "").upper() != "PY"
            or adapter.environment != "test"
            or adapter.tenant_id != document.tenant_id
            or adapter.company_id != document.company_id
            or not adapter.sequence_id
        ):
            raise ValidationError(
                "SIFEN Consulta DE requires matching adapter configuration."
            )
        query_id = adapter.sequence_id.next_by_id()
        if not query_id or not query_id.isdigit() or len(query_id) > 15:
            raise ValidationError(
                "SIFEN Consulta DE dId must contain 1 to 15 digits."
            )
        return query_id

    def _returned_content(self, response_node):
        container = response_node.find(
            f"{{{self.SIFEN_NS}}}xContenDE",
        )
        structure = {
            "container_present": container is not None,
            "container_namespace": self.SIFEN_NS if container is not None else "",
            "direct_children": [],
            "text_present": False,
            "embedded_xml_parseable": False,
            "embedded_root": None,
            "de_candidate_count": 0,
            "returned_cdc": "",
            "protocol_present": False,
            "text_length": 0,
            "text_sha256": "",
            "xml_declaration_present": False,
            "xml_declaration_removed": False,
            "xml_declaration_valid": False,
            "declaration_has_encoding": False,
            "declaration_has_standalone": False,
        }
        if container is None:
            return None, structure

        direct_children = list(container)
        structure["direct_children"] = [
            self._node_identity(node) for node in direct_children[:20]
        ]
        structure["direct_children_truncated"] = len(direct_children) > 20
        exact_text = container.text or ""
        text = exact_text.strip()
        structure["text_present"] = bool(text)
        if exact_text:
            structure["text_length"] = len(exact_text)
            structure["text_sha256"] = hashlib.sha256(
                exact_text.encode("utf-8")
            ).hexdigest()
        if direct_children or not text:
            return None, structure
        normalized, declaration_metadata = self._normalize_embedded_xml_text(
            exact_text
        )
        structure.update(declaration_metadata)
        if normalized is None:
            return None, structure
        try:
            roots = [self._parse_xml(normalized)]
        except (TypeError, ValueError, etree.XMLSyntaxError):
            return None, structure
        structure["embedded_xml_parseable"] = True
        structure["embedded_root"] = self._node_identity(roots[0])

        candidates = []
        protocols = []
        for root in roots:
            for node in root.iter():
                qname = etree.QName(node)
                if qname.namespace not in {None, "", self.SIFEN_NS}:
                    continue
                if qname.localname == "DE":
                    candidates.append(node)
                elif qname.localname == "dProtAut":
                    value = (node.text or "").strip()
                    if value:
                        protocols.append(value)
        structure["de_candidate_count"] = len(candidates)
        structure["protocol_present"] = bool(protocols)
        if len(candidates) != 1:
            return None, structure
        cdc = (candidates[0].get("Id") or "").strip()
        if not cdc.isdigit() or len(cdc) != 44 or len(protocols) > 1:
            return None, structure
        structure["returned_cdc"] = cdc
        return (cdc, protocols[0] if protocols else ""), structure

    def _normalize_embedded_xml_text(self, value):
        normalized = value.lstrip("\ufeff \t\r\n")
        metadata = {
            "xml_declaration_present": normalized.startswith("<?xml"),
            "xml_declaration_removed": False,
            "xml_declaration_valid": False,
            "declaration_has_encoding": False,
            "declaration_has_standalone": False,
        }
        if metadata["xml_declaration_present"]:
            declaration_end = normalized.find("?>")
            if declaration_end < 0:
                return None, metadata
            declaration_text = normalized[:declaration_end + 2]
            declaration = self._XML_DECLARATION_RE.fullmatch(declaration_text)
            if declaration is None:
                return None, metadata
            metadata.update({
                "xml_declaration_removed": True,
                "xml_declaration_valid": True,
                "declaration_has_encoding": bool(
                    declaration.group("encoding")
                ),
                "declaration_has_standalone": bool(
                    declaration.group("standalone")
                ),
            })
            normalized = normalized[declaration_end + 2:].lstrip()
        if not normalized:
            return None, metadata
        return normalized, metadata

    def _node_identity(self, node):
        qname = etree.QName(node)
        return {
            "local_name": qname.localname[:100],
            "namespace": (qname.namespace or "")[:200],
        }

    def _parse_xml(self, content):
        parser = etree.XMLParser(
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
        )
        return etree.fromstring(content, parser=parser)

    def _direct_text(self, node, name):
        child = node.find(f"{{{self.SIFEN_NS}}}{name}")
        return (child.text or "").strip() if child is not None else ""

    def _response_status_code(self, response):
        if isinstance(response, dict):
            return int(
                response.get("status_code")
                or response.get("http_status")
                or 0
            )
        return int(
            getattr(response, "status_code", None)
            or getattr(response, "code", None)
            or 0
        )

    def _response_content(self, response):
        if isinstance(response, dict):
            content = response.get("content") or response.get("body") or b""
        else:
            content = (
                getattr(response, "content", None)
                or getattr(response, "body", None)
                or b""
            )
        return content.encode("utf-8") if isinstance(content, str) else content

    def _create_transmission(self, *, document, cdc, started_at):
        return self.env["fiscal.transmission"].sudo().create({
            "document_id": document.id,
            "transmission_type": "status_query",
            "state": "pending",
            "country_code": "PY",
            "environment": "test",
            "country_identifier": cdc,
            "attempt_number": self._next_attempt_number(document),
            "started_at": started_at,
        })

    def _finish_transmission(self, *, transmission, result, finished_at):
        if result.get("approved"):
            state = "accepted"
        elif result.get("not_approved"):
            state = "manual_review"
        elif result.get("retryable"):
            state = "failed_retryable"
        else:
            state = "failed_final"
        transmission.write({
            "state": state,
            "request_hash": result.get("request_hash") or "",
            "response_hash": result.get("response_hash") or "",
            "http_status": result.get("http_status") or 0,
            "duration_ms": result.get("duration_ms") or 0,
            "endpoint_url": result.get("endpoint_url") or "",
            "authority_status_code": result.get("authority_code") or "",
            "authority_message": result.get("authority_message") or "",
            "error_code": (
                "reconciliation_not_found"
                if result.get("not_approved")
                else "" if result.get("ok")
                else result.get("category") or "consulta_failure"
            ),
            "error_message": (
                "SIFEN Consulta DE did not find an approved DTE; operator decision is required."
                if result.get("not_approved")
                else "" if result.get("ok")
                else "SIFEN Consulta DE could not resolve the submission."
            ),
            "error_type": "" if result.get("ok") else "sifen_consulta_de",
            "finished_at": finished_at,
            "metadata_json": json.dumps({
                "result_category": result.get("category") or "",
                "authority_timestamp": result.get("authority_timestamp") or "",
                "response_structure": result.get("response_structure") or {},
                "normalized_response": {
                    "authority_code": result.get("authority_code") or "",
                    "authority_message": result.get("authority_message") or "",
                    "approved": bool(result.get("approved")),
                    "not_found": bool(result.get("not_approved")),
                },
            }, sort_keys=True),
        })

    def _next_attempt_number(self, document):
        attempts = document.transmission_ids.filtered(
            lambda item: item.transmission_type == "status_query"
        ).mapped("attempt_number")
        return max(attempts or [0]) + 1

    def _failure_result(self, *, category, message, retryable):
        return {
            "ok": False,
            "category": category,
            "http_status": 0,
            "request_hash": "",
            "response_hash": "",
            "authority_code": "",
            "authority_message": message,
            "authority_receipt_ref": "",
            "approved": False,
            "not_approved": False,
            "retryable": retryable,
            "authority_timestamp": "",
        }

    def _safe_endpoint(self, value):
        parsed = urlsplit(value or "")
        if parsed.scheme != "https" or not parsed.hostname:
            return ""
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


# Backward-compatible Stage 8.24A name.
PySifenConsultaDeService = PySifenDocumentQueryService
