from dataclasses import dataclass, field
from enum import Enum

from lxml import etree

from odoo.addons.einvoice_py.services.py_sifen_soap_client import (
    PySifenSoapClientResult,
)


class PySifenRecepDeClassification(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PROCESSING_PENDING = "processing_pending"
    DUPLICATE = "duplicate"
    SOAP_FAULT = "soap_fault"
    HTTP_ERROR = "http_error"
    MALFORMED_RESPONSE = "malformed_response"
    UNRECOGNIZED_OFFICIAL_CODE = "unrecognized_official_code"


@dataclass(frozen=True, slots=True)
class PySifenRecepDeOfficialResult:
    code: str | None
    message: str | None


@dataclass(frozen=True, slots=True, repr=False)
class PySifenRecepDeResponseResult:
    http_status: int
    raw_response_bytes: bytes = field(repr=False)
    parsed_xml: object | None = field(repr=False, compare=False)
    soap_fault: bool
    soap_fault_code: str | None
    soap_fault_subcode: str | None
    soap_fault_reason: str | None
    soap_fault_detail: str | None = field(repr=False)
    response_identifier: str | None
    request_identifier: str | None
    processing_datetime: str | None
    result_code: str | None
    result_message: str | None
    protocol_receipt: str | None
    cdc: str | None
    classification: PySifenRecepDeClassification
    parse_warnings: tuple
    endpoint_url: str
    elapsed_ms: int
    official_results: tuple

    def __repr__(self):
        return (
            "PySifenRecepDeResponseResult("
            f"http_status={self.http_status!r}, "
            f"soap_fault={self.soap_fault!r}, "
            f"response_identifier={self.response_identifier!r}, "
            f"result_code={self.result_code!r}, "
            f"classification={self.classification.value!r}, "
            f"elapsed_ms={self.elapsed_ms!r}, "
            "raw_response_bytes=<redacted>, parsed_xml=<redacted>, "
            "soap_fault_detail=<redacted>, endpoint_url=<redacted>)"
        )

    __str__ = __repr__


class PySifenRecepDeResponseParser:
    """Parse an official synchronous SIFEN ``siRecepDE`` SOAP response."""

    SOAP_ENV_NS = "http://www.w3.org/2003/05/soap-envelope"
    SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
    NS = {"soap": SOAP_ENV_NS, "sifen": SIFEN_NS}

    ACCEPTED_CODE = "0260"
    DUPLICATE_CODES = frozenset({"1001", "1002"})
    ACCEPTED_STATUSES = frozenset({"Aprobado", "Aprobado con observación"})
    REJECTED_STATUS = "Rechazado"

    def parse(self, client_result):
        if not isinstance(client_result, PySifenSoapClientResult):
            raise TypeError("A PySifenSoapClientResult is required.")

        raw = client_result.raw_response_bytes
        if not raw:
            return self._non_business_result(
                client_result,
                classification=self._http_or_malformed(client_result),
                warning="SIFEN returned an empty response body.",
            )

        try:
            root = self._parse_xml(raw)
        except (TypeError, ValueError, etree.XMLSyntaxError):
            return self._non_business_result(
                client_result,
                classification=self._http_or_malformed(client_result),
                warning="SIFEN returned a non-XML or malformed response body.",
            )

        envelope_tag = f"{{{self.SOAP_ENV_NS}}}Envelope"
        body_tag = f"{{{self.SOAP_ENV_NS}}}Body"
        if root.tag != envelope_tag:
            return self._malformed(
                client_result,
                root,
                "SIFEN response must use the SOAP 1.2 Envelope namespace.",
            )
        bodies = root.findall(body_tag)
        if len(bodies) != 1:
            return self._malformed(
                client_result,
                root,
                "SIFEN SOAP response must contain exactly one Body.",
            )
        body_children = list(bodies[0])
        if len(body_children) != 1:
            return self._malformed(
                client_result,
                root,
                "SIFEN SOAP Body must contain exactly one response element.",
            )

        if body_children[0].tag == f"{{{self.SOAP_ENV_NS}}}Fault":
            return self._soap_fault_result(client_result, root, body_children[0])
        if body_children[0].tag != f"{{{self.SIFEN_NS}}}rRetEnviDe":
            return self._malformed(
                client_result,
                root,
                "SIFEN SOAP Body must contain rRetEnviDe.",
            )
        return self._business_result(client_result, root, body_children[0])

    def _business_result(self, client_result, root, wrapper):
        protocols = wrapper.findall(f"{{{self.SIFEN_NS}}}rProtDe")
        if len(protocols) != 1 or len(wrapper) != 1:
            return self._malformed(
                client_result,
                root,
                "SIFEN rRetEnviDe must contain exactly one rProtDe.",
            )
        protocol = protocols[0]
        allowed_tags = {
            f"{{{self.SIFEN_NS}}}Id",
            f"{{{self.SIFEN_NS}}}dFecProc",
            f"{{{self.SIFEN_NS}}}dDigVal",
            f"{{{self.SIFEN_NS}}}dEstRes",
            f"{{{self.SIFEN_NS}}}dProtAut",
            f"{{{self.SIFEN_NS}}}gResProc",
        }
        if any(child.tag not in allowed_tags for child in protocol):
            return self._malformed(
                client_result,
                root,
                "SIFEN rProtDe contains an unexpected response element.",
            )
        tag_order = {
            f"{{{self.SIFEN_NS}}}Id": 0,
            f"{{{self.SIFEN_NS}}}dFecProc": 1,
            f"{{{self.SIFEN_NS}}}dDigVal": 2,
            f"{{{self.SIFEN_NS}}}dEstRes": 3,
            f"{{{self.SIFEN_NS}}}dProtAut": 4,
            f"{{{self.SIFEN_NS}}}gResProc": 5,
        }
        positions = [tag_order[child.tag] for child in protocol]
        if positions != sorted(positions):
            return self._malformed(
                client_result,
                root,
                "SIFEN rProtDe fields do not follow the official XSD order.",
            )

        singular_names = ("Id", "dFecProc", "dDigVal", "dEstRes", "dProtAut")
        values = {}
        for name in singular_names:
            nodes = protocol.findall(f"{{{self.SIFEN_NS}}}{name}")
            if len(nodes) > 1:
                return self._malformed(
                    client_result,
                    root,
                    f"SIFEN rProtDe contains duplicate {name} fields.",
                )
            values[name] = self._node_text(nodes[0]) if nodes else None
        if not values["dFecProc"]:
            return self._malformed(
                client_result,
                root,
                "SIFEN rProtDe must contain dFecProc.",
            )

        result_nodes = protocol.findall(f"{{{self.SIFEN_NS}}}gResProc")
        if len(result_nodes) > 100:
            return self._malformed(
                client_result,
                root,
                "SIFEN rProtDe contains too many gResProc elements.",
            )
        official_results = []
        for result_node in result_nodes:
            if any(
                child.tag not in {
                    f"{{{self.SIFEN_NS}}}dCodRes",
                    f"{{{self.SIFEN_NS}}}dMsgRes",
                }
                for child in result_node
            ):
                return self._malformed(
                    client_result,
                    root,
                    "SIFEN gResProc contains an unexpected response element.",
                )
            code_nodes = result_node.findall(f"{{{self.SIFEN_NS}}}dCodRes")
            message_nodes = result_node.findall(f"{{{self.SIFEN_NS}}}dMsgRes")
            if len(code_nodes) > 1 or len(message_nodes) > 1:
                return self._malformed(
                    client_result,
                    root,
                    "SIFEN gResProc contains duplicate result fields.",
                )
            official_results.append(PySifenRecepDeOfficialResult(
                code=self._node_text(code_nodes[0]) if code_nodes else None,
                message=self._node_text(message_nodes[0]) if message_nodes else None,
            ))

        warnings = []
        if not values["Id"]:
            warnings.append(
                "The official response omitted optional rProtDe/Id."
            )
        if not official_results:
            warnings.append(
                "The official response omitted optional gResProc."
            )
        primary = official_results[0] if official_results else None
        code = primary.code if primary else None
        message = primary.message if primary else None
        classification, classification_warning = self._classify(
            status=values["dEstRes"],
            codes=tuple(item.code for item in official_results if item.code),
        )
        if classification_warning:
            warnings.append(classification_warning)
        if len(official_results) > 1:
            warnings.append(
                "Additional official processing results are available in "
                "official_results."
            )
        if client_result.http_status >= 400:
            classification = PySifenRecepDeClassification.HTTP_ERROR
            warnings.append(
                "HTTP error classification takes precedence over business fields."
            )

        return PySifenRecepDeResponseResult(
            http_status=client_result.http_status,
            raw_response_bytes=client_result.raw_response_bytes,
            parsed_xml=root,
            soap_fault=False,
            soap_fault_code=None,
            soap_fault_subcode=None,
            soap_fault_reason=None,
            soap_fault_detail=None,
            response_identifier=values["Id"],
            request_identifier=client_result.request_identifier or None,
            processing_datetime=values["dFecProc"],
            result_code=code,
            result_message=message,
            protocol_receipt=values["dProtAut"],
            cdc=values["Id"],
            classification=classification,
            parse_warnings=tuple(warnings),
            endpoint_url=client_result.endpoint_url,
            elapsed_ms=client_result.elapsed_ms,
            official_results=tuple(official_results),
        )

    def _classify(self, *, status, codes):
        code_set = frozenset(codes)
        accepted = status in self.ACCEPTED_STATUSES or self.ACCEPTED_CODE in code_set
        duplicate = bool(code_set & self.DUPLICATE_CODES)
        rejected = status == self.REJECTED_STATUS
        if accepted and (duplicate or rejected):
            return (
                PySifenRecepDeClassification.MALFORMED_RESPONSE,
                "SIFEN response contains conflicting status and result codes.",
            )
        if duplicate:
            return PySifenRecepDeClassification.DUPLICATE, None
        if accepted:
            return PySifenRecepDeClassification.ACCEPTED, None
        if rejected:
            return PySifenRecepDeClassification.REJECTED, None
        return (
            PySifenRecepDeClassification.UNRECOGNIZED_OFFICIAL_CODE,
            "SIFEN response status or result code is not mapped.",
        )

    def _soap_fault_result(self, client_result, root, fault):
        code_node = fault.find("soap:Code/soap:Value", self.NS)
        subcode_node = fault.find("soap:Code/soap:Subcode/soap:Value", self.NS)
        reason_nodes = fault.findall("soap:Reason/soap:Text", self.NS)
        detail_node = fault.find("soap:Detail", self.NS)
        warnings = []
        if len(reason_nodes) > 1:
            warnings.append(
                "SOAP Fault contains multiple localized Reason values; the first "
                "value was selected."
            )
        return PySifenRecepDeResponseResult(
            http_status=client_result.http_status,
            raw_response_bytes=client_result.raw_response_bytes,
            parsed_xml=root,
            soap_fault=True,
            soap_fault_code=self._node_text(code_node),
            soap_fault_subcode=self._node_text(subcode_node),
            soap_fault_reason=(
                self._node_text(reason_nodes[0]) if reason_nodes else None
            ),
            soap_fault_detail=(
                etree.tostring(detail_node, encoding="unicode")
                if detail_node is not None
                else None
            ),
            response_identifier=None,
            request_identifier=client_result.request_identifier or None,
            processing_datetime=None,
            result_code=None,
            result_message=None,
            protocol_receipt=None,
            cdc=None,
            classification=PySifenRecepDeClassification.SOAP_FAULT,
            parse_warnings=tuple(warnings),
            endpoint_url=client_result.endpoint_url,
            elapsed_ms=client_result.elapsed_ms,
            official_results=(),
        )

    def _malformed(self, client_result, root, warning):
        return self._result(
            client_result,
            parsed_xml=root,
            classification=(
                PySifenRecepDeClassification.HTTP_ERROR
                if client_result.http_status >= 400
                else PySifenRecepDeClassification.MALFORMED_RESPONSE
            ),
            warnings=(warning,),
        )

    def _non_business_result(self, client_result, *, classification, warning):
        return self._result(
            client_result,
            parsed_xml=None,
            classification=classification,
            warnings=(warning,),
        )

    def _result(self, client_result, *, parsed_xml, classification, warnings):
        return PySifenRecepDeResponseResult(
            http_status=client_result.http_status,
            raw_response_bytes=client_result.raw_response_bytes,
            parsed_xml=parsed_xml,
            soap_fault=False,
            soap_fault_code=None,
            soap_fault_subcode=None,
            soap_fault_reason=None,
            soap_fault_detail=None,
            response_identifier=None,
            request_identifier=client_result.request_identifier or None,
            processing_datetime=None,
            result_code=None,
            result_message=None,
            protocol_receipt=None,
            cdc=None,
            classification=classification,
            parse_warnings=warnings,
            endpoint_url=client_result.endpoint_url,
            elapsed_ms=client_result.elapsed_ms,
            official_results=(),
        )

    def _http_or_malformed(self, client_result):
        if client_result.http_status >= 400:
            return PySifenRecepDeClassification.HTTP_ERROR
        return PySifenRecepDeClassification.MALFORMED_RESPONSE

    def _parse_xml(self, content):
        if isinstance(content, str):
            content = content.encode("utf-8")
        parser = etree.XMLParser(
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            remove_blank_text=False,
        )
        return etree.fromstring(content, parser)

    def _node_text(self, node):
        if node is None:
            return None
        value = (node.text or "").strip()
        return value or None
