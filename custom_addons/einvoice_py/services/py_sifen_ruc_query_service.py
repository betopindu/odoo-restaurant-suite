import hashlib
import logging
import re
import time

from lxml import etree

from odoo import fields
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_credential_provider import (
    PySifenCredentialProvider,
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


_logger = logging.getLogger(__name__)


class PySifenRucQueryService:
    """Resolve a receiver locally first and use the official Consulta RUC as fallback."""

    SOAP_ENV_NS = "http://www.w3.org/2003/05/soap-envelope"
    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS
    ENDPOINTS = {
        "test": "https://sifen-test.set.gov.py/de/ws/consultas/consulta-ruc.wsdl",
        "production": "https://sifen.set.gov.py/de/ws/consultas/consulta-ruc.wsdl",
    }
    RUC_RE = re.compile(r"^(?P<number>[0-9]{5,8})(?:-(?P<dv>[0-9]))?$")

    def __init__(self, env, *, credential_provider=None, transport=None, clock=None):
        self.env = env
        self.credential_provider = credential_provider or PySifenCredentialProvider(env)
        self.transport = transport or PySifenSandboxTransport(env)
        self.clock = clock or time.monotonic

    def resolve(self, *, adapter_config, company, ruc, allow_remote=True):
        company.ensure_one()
        number, dv = self.normalize_ruc(ruc)
        partner = self._local_partner(company=company, number=number, dv=dv)
        if partner:
            return self._partner_result(partner, source="local")
        if not allow_remote:
            return self._manual_result(number, dv, "local_not_found")
        adapter_config.ensure_one()
        self._validate_scope(adapter_config=adapter_config, company=company)
        started = self.clock()
        try:
            credentials = self.credential_provider.resolve_event(
                adapter_config=adapter_config
            )
            request_xml = self.build_request(
                adapter_config=adapter_config,
                ruc_number=number,
            )
            response = self.transport(
                endpoint_url=self.ENDPOINTS[adapter_config.environment],
                body=request_xml,
                timeout_seconds=credentials.timeout_seconds,
                mutual_tls_credential=credentials.mutual_tls_credential,
            )
            result = self.normalize_response(response=response, expected_ruc=number)
        except PySifenTransportError:
            return self._manual_result(number, dv, "authority_unavailable")
        except ValidationError:
            raise
        except Exception:
            return self._manual_result(number, dv, "authority_unavailable")
        result.update({
            "duration_ms": max(0, int((self.clock() - started) * 1000)),
            "ruc": self.full_ruc(number, dv),
        })
        if result["status"] != "found":
            return result
        partner = self._persist_authority_partner(
            company=company,
            number=number,
            dv=dv,
            result=result,
        )
        return self._partner_result(
            partner,
            source="authority",
            authority_code=result["authority_code"],
            authority_message=result["authority_message"],
        )

    @classmethod
    def normalize_ruc(cls, value):
        normalized = re.sub(r"\s+", "", str(value or ""))
        match = cls.RUC_RE.fullmatch(normalized)
        if not match or not match.group("dv"):
            raise ValidationError("Enter a Paraguay RUC with verification digit (for example 80012345-6).")
        return match.group("number"), match.group("dv")

    @staticmethod
    def full_ruc(number, dv):
        return f"{number}-{dv}"

    def build_request(self, *, adapter_config, ruc_number):
        query_id = self._next_query_id(adapter_config)
        envelope = etree.Element(
            f"{{{self.SOAP_ENV_NS}}}Envelope",
            nsmap={"soap": self.SOAP_ENV_NS, "sifen": self.SIFEN_NS},
        )
        body = etree.SubElement(envelope, f"{{{self.SOAP_ENV_NS}}}Body")
        request_node = etree.SubElement(body, f"{{{self.SIFEN_NS}}}rEnviConsRUC")
        etree.SubElement(request_node, f"{{{self.SIFEN_NS}}}dId").text = query_id
        etree.SubElement(request_node, f"{{{self.SIFEN_NS}}}dRUCCons").text = ruc_number
        return etree.tostring(envelope, encoding="UTF-8", xml_declaration=True)

    def normalize_response(self, *, response, expected_ruc):
        status_code = self._status_code(response)
        content = self._content(response)
        diagnostic = self._response_diagnostic(response=response, content=content)
        base = {
            "status": "manual_required",
            "authority_code": "",
            "authority_message": "",
            "reason": "authority_invalid_response",
            "response_hash": hashlib.sha256(content).hexdigest() if content else "",
            "http_status": status_code,
            "response_diagnostic": diagnostic,
        }
        if not content or not 200 <= status_code < 300:
            _logger.warning(
                "SIFEN Consulta RUC returned an invalid HTTP response: "
                "status=%s diagnostic=%s",
                status_code,
                diagnostic,
            )
            return base
        try:
            root = etree.fromstring(
                content,
                parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True),
            )
        except (TypeError, ValueError, etree.XMLSyntaxError):
            _logger.warning(
                "SIFEN Consulta RUC returned malformed XML: status=%s diagnostic=%s",
                status_code,
                diagnostic,
            )
            return base
        node = root.find(f".//{{{self.SIFEN_NS}}}rResEnviConsRUC")
        if node is None:
            return base
        code = self._text(node, "dCodRes")
        message = self._text(node, "dMsgRes")
        base.update({"authority_code": code, "authority_message": message})
        if code == "0500":
            base.update({"status": "manual_required", "reason": "authority_not_found"})
            return base
        if code != "0502":
            base["reason"] = "authority_unavailable" if code == "0501" else "authority_invalid_response"
            return base
        container = node.find(f"{{{self.SIFEN_NS}}}xContRUC")
        if container is None:
            return base
        returned_ruc = self._text(container, "dRUCCons")
        name = self._text(container, "dRazCons")
        state_code = self._text(container, "dCodEstCons")
        state_name = self._text(container, "dDesEstCons")
        electronic_issuer = self._text(container, "dRUCFactElec")
        if returned_ruc != expected_ruc or not name:
            return base
        base.update({
            "status": "found",
            "reason": "",
            "name": name,
            "returned_ruc": returned_ruc,
            "taxpayer_state_code": state_code,
            "taxpayer_state": state_name,
            "electronic_issuer": electronic_issuer,
        })
        return base

    @classmethod
    def _response_diagnostic(cls, *, response, content):
        """Return allow-listed response structure without response payload data."""
        headers = response.get("headers", {}) if isinstance(response, dict) else {}
        normalized_headers = {
            str(key).lower(): str(value)
            for key, value in (headers or {}).items()
        }
        raw_content_type = normalized_headers.get("content-type", "")
        media_type = raw_content_type.split(";", 1)[0].strip().lower()
        allowed_media_types = {
            "application/soap+xml",
            "application/xml",
            "text/xml",
            "text/html",
            "text/plain",
        }
        safe_media_type = media_type if media_type in allowed_media_types else (
            "other" if media_type else "absent"
        )
        diagnostic = {
            "category": "empty" if not content else "binary_or_text",
            "content_type": safe_media_type,
            "byte_length": len(content),
        }
        if not content:
            return diagnostic
        if safe_media_type == "text/html":
            diagnostic["category"] = "html"
            return diagnostic
        try:
            root = etree.fromstring(
                content,
                parser=etree.XMLParser(
                    resolve_entities=False,
                    load_dtd=False,
                    no_network=True,
                ),
            )
        except (TypeError, ValueError, etree.XMLSyntaxError):
            if safe_media_type in {"application/xml", "application/soap+xml", "text/xml"}:
                diagnostic["category"] = "malformed_xml"
            elif safe_media_type == "text/plain":
                diagnostic["category"] = "plain_text"
            return diagnostic
        qname = etree.QName(root)
        diagnostic.update({
            "category": "xml",
            "root_local_name": qname.localname[:64],
            "namespace_category": cls._namespace_category(qname.namespace),
        })
        return diagnostic

    @classmethod
    def _namespace_category(cls, namespace):
        if namespace == cls.SOAP_ENV_NS:
            return "soap12"
        if namespace == cls.SIFEN_NS:
            return "sifen"
        return "other"

    def create_manual_partner(self, *, company, ruc, name, taxpayer_type, email=None):
        company.ensure_one()
        number, dv = self.normalize_ruc(ruc)
        name = (name or "").strip()
        if not name:
            raise ValidationError("Manual RUC entry requires the customer name.")
        if taxpayer_type not in ("1", "2"):
            raise ValidationError("Manual RUC entry requires person or legal-entity type.")
        existing = self._local_partner(company=company, number=number, dv=dv)
        if existing:
            return self._partner_result(existing, source="local")
        partner = self.env["res.partner"].create({
            "name": name,
            "vat": self.full_ruc(number, dv),
            "company_id": company.id,
            "email": (email or "").strip() or False,
            "py_sifen_receiver_profile": "taxpayer",
            "py_sifen_taxpayer_type": taxpayer_type,
            "py_sifen_ruc_resolution": "manual_unverified",
        })
        return self._partner_result(partner, source="manual_unverified")

    def _persist_authority_partner(self, *, company, number, dv, result):
        return self.env["res.partner"].create({
            "name": result["name"],
            "vat": self.full_ruc(number, dv),
            "company_id": company.id,
            "py_sifen_receiver_profile": "taxpayer",
            "py_sifen_ruc_resolution": "authority",
            "py_sifen_ruc_status_code": result["taxpayer_state_code"],
            "py_sifen_ruc_status": result["taxpayer_state"],
            "py_sifen_ruc_electronic_issuer": result["electronic_issuer"],
            "py_sifen_ruc_checked_at": fields.Datetime.now(),
        })

    def _local_partner(self, *, company, number, dv):
        variants = [self.full_ruc(number, dv), number]
        partners = self.env["res.partner"].search([
            ("vat", "in", variants),
            ("company_id", "in", [False, company.id]),
            ("py_sifen_receiver_profile", "=", "taxpayer"),
        ], limit=2)
        exact = partners.filtered(
            lambda partner: re.sub(r"\s+", "", partner.vat or "") == variants[0]
        )
        return exact[:1]

    def _partner_result(self, partner, *, source, authority_code="", authority_message=""):
        return {
            "status": "found",
            "source": source,
            "partner_id": partner.id,
            "name": partner.name,
            "ruc": partner.vat,
            "email": partner.email or "",
            "taxpayer_type": partner.py_sifen_taxpayer_type or "",
            "authority_code": authority_code,
            "authority_message": authority_message,
        }

    def _manual_result(self, number, dv, reason):
        return {
            "status": "manual_required",
            "source": "",
            "reason": reason,
            "ruc": self.full_ruc(number, dv),
            "authority_code": "",
            "authority_message": "",
        }

    def _validate_scope(self, *, adapter_config, company):
        if (
            not adapter_config.active
            or (adapter_config.country_code or "").upper() != "PY"
            or adapter_config.environment not in self.ENDPOINTS
            or adapter_config.company_id != company
            or not adapter_config.sequence_id
        ):
            raise ValidationError("Paraguay Consulta RUC configuration is invalid.")

    def _next_query_id(self, adapter_config):
        query_id = adapter_config.sequence_id.next_by_id()
        if not query_id or not query_id.isdigit() or len(query_id) > 15:
            raise ValidationError("Consulta RUC dId must contain 1 to 15 digits.")
        return query_id

    def _text(self, node, name):
        child = node.find(f"{{{self.SIFEN_NS}}}{name}")
        return (child.text or "").strip() if child is not None else ""

    @staticmethod
    def _status_code(response):
        if isinstance(response, dict):
            return int(response.get("status_code") or response.get("http_status") or 0)
        return int(getattr(response, "status_code", 0) or 0)

    @staticmethod
    def _content(response):
        if isinstance(response, dict):
            return response.get("content") or b""
        return getattr(response, "content", b"") or b""
