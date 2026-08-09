import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from lxml import etree
from odoo import fields
from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_credential_provider import PySifenCredentialProvider
from odoo.addons.einvoice_py.services.py_sifen_datetime_service import PySifenDatetimeService
from odoo.addons.einvoice_py.services.py_sifen_event_signature_service import PySifenEventSignatureService
from odoo.addons.einvoice_py.services.py_sifen_sandbox_transport import PySifenSandboxTransport
from odoo.addons.einvoice_py.services.py_sifen_test_submission_service import PySifenTransportError


class PySifenEventService:
    SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
    SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
    ENDPOINTS = {
        "test": "https://sifen-test.set.gov.py/de/ws/eventos/evento.wsdl",
        "production": "https://sifen.set.gov.py/de/ws/eventos/evento.wsdl",
    }
    ACCEPTED_CODE = "0600"

    def __init__(self, env, *, credential_provider=None, signer=None, transport=None):
        self.env = env
        self.credential_provider = credential_provider or PySifenCredentialProvider(env)
        self.signer = signer or PySifenEventSignatureService()
        self.transport = transport or PySifenSandboxTransport(env)

    def execute(self, *, adapter, event_xml_bytes, audit_record, audit_model, original_ids=None):
        started = time.monotonic()
        endpoint = self.ENDPOINTS[adapter.environment]
        request_hash = ""
        event_id = ""
        try:
            credentials = self.credential_provider.resolve_event(adapter_config=adapter)
            signed = self.signer.sign(
                event_xml_bytes=event_xml_bytes,
                certificate_bytes=credentials.signing_certificate_bytes,
                private_key_bytes=credentials.signing_private_key_bytes,
                private_key_password=credentials.signing_private_key_password,
            )
            event_id = signed.event_id
            request_xml = self._envelope(adapter, signed.signed_xml_bytes)
            request_hash = hashlib.sha256(request_xml).hexdigest()
            response = self.transport(
                endpoint_url=endpoint,
                body=request_xml,
                timeout_seconds=credentials.timeout_seconds,
                mutual_tls_credential=credentials.mutual_tls_credential,
            )
            result = self._parse_response(response)
        except PySifenTransportError:
            result = self._failure("transport_ambiguous", "SIFEN event transport outcome is ambiguous.", True)
        except ValidationError:
            result = self._failure("configuration_invalid", "SIFEN event configuration is invalid.", False)
        except Exception:
            result = self._failure("event_failure", "SIFEN event could not be completed.", False)
        result.update({
            "request_hash": request_hash,
            "event_id": event_id,
            "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
            "endpoint_url": self._safe_endpoint(endpoint),
        })
        self._persist_result(audit_record, audit_model, result, original_ids or [])
        return result

    def build_cancellation_event(self, *, event_id, cdc, reason, signing_timestamp):
        group = self._event_root(event_id, signing_timestamp)
        kind = etree.SubElement(group, self._tag("rGeVeCan"))
        self._text(kind, "Id", cdc)
        self._text(kind, "mOtEve", reason)
        return etree.tostring(group.getroottree().getroot(), encoding="UTF-8", xml_declaration=True)

    def build_inutilization_event(self, *, event_id, timbrado, establishment, point, number_from, number_to, document_type_code, reason, signing_timestamp):
        group = self._event_root(event_id, signing_timestamp)
        kind = etree.SubElement(group, self._tag("rGeVeInu"))
        for name, value in (
            ("dNumTim", timbrado), ("dEst", establishment), ("dPunExp", point),
            ("dNumIn", str(number_from).zfill(7)), ("dNumFin", str(number_to).zfill(7)),
            ("iTiDE", document_type_code), ("mOtEve", reason),
        ):
            self._text(kind, name, value)
        return etree.tostring(group.getroottree().getroot(), encoding="UTF-8", xml_declaration=True)

    def _event_root(self, event_id, signing_timestamp):
        root = etree.Element(self._tag("rGesEve"), nsmap={None: self.SIFEN_NS})
        event = etree.SubElement(root, self._tag("rEve"), Id=event_id)
        self._text(event, "dFecFirma", PySifenDatetimeService.format_signing_datetime(signing_timestamp))
        self._text(event, "dVerFor", "150")
        return etree.SubElement(event, self._tag("gGroupTiEvt"))

    def _envelope(self, adapter, signed_event):
        root = etree.Element(self._soap_tag("Envelope"), nsmap={"soap": self.SOAP_NS, "sifen": self.SIFEN_NS})
        body = etree.SubElement(root, self._soap_tag("Body"))
        request = etree.SubElement(body, self._tag("rEnviEventoDe"))
        self._text(request, "dId", self._next_id(adapter, 15))
        registered = etree.SubElement(request, self._tag("dEvReg"))
        group = etree.SubElement(registered, self._tag("gGroupGesEve"))
        group.append(etree.fromstring(signed_event))
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    def _parse_response(self, response):
        status = int(response.get("status_code") or 0)
        content = response.get("content") or b""
        response_hash = hashlib.sha256(content).hexdigest() if content else ""
        base = self._failure("malformed_response", "SIFEN event response was malformed.", True)
        base.update({"http_status": status, "response_hash": response_hash})
        if not content:
            return base
        try:
            root = etree.fromstring(content, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        except etree.XMLSyntaxError:
            return base
        if root.find(f".//{{{self.SOAP_NS}}}Fault") is not None:
            base.update({"category": "soap_fault", "authority_message": "SIFEN event returned a SOAP Fault.", "ambiguous": True})
            return base
        response_node = root.find(f".//{self._tag('rRetEnviEventoDe')}")
        result_node = response_node.find(self._tag("gResProcEVe")) if response_node is not None else None
        process = result_node.find(self._tag("gResProc")) if result_node is not None else None
        if process is None:
            return base
        code = self._value(process, "dCodRes")
        message = self._value(process, "dMsgRes")
        if not 200 <= status < 300:
            base.update({
                "category": "http_failure", "authority_code": code,
                "authority_message": message or "SIFEN event HTTP response was unsuccessful.",
                "ambiguous": True,
            })
            return base
        accepted = code == self.ACCEPTED_CODE and 200 <= status < 300
        return {
            "ok": accepted, "accepted": accepted, "ambiguous": False,
            "category": "accepted" if accepted else "rejected",
            "http_status": status, "response_hash": response_hash,
            "authority_code": code, "authority_message": message,
            "authority_protocol": self._value(result_node, "dProtAut"),
            "authority_timestamp": self._value(response_node, "dFecProc"),
        }

    def _persist_result(self, record, model_name, result, original_ids):
        state = "accepted" if result.get("accepted") else "manual_review" if result.get("ambiguous") else "rejected"
        common = {
            "state": state, "endpoint_url": result.get("endpoint_url") or "",
            "request_hash": result.get("request_hash") or "", "response_hash": result.get("response_hash") or "",
            "http_status": result.get("http_status") or 0, "duration_ms": result.get("duration_ms") or 0,
            "finished_at": fields.Datetime.now(),
        }
        metadata = json.dumps({
            "result_category": result.get("category"),
            "event_id": result.get("event_id") or "",
            "authority_protocol": result.get("authority_protocol") or "",
            "authority_timestamp": result.get("authority_timestamp") or "",
            "original_evidence_ids": original_ids,
            "ambiguous": bool(result.get("ambiguous")),
        }, sort_keys=True)
        if model_name == "fiscal.transmission":
            common.update({
                "authority_status_code": result.get("authority_code") or "", "authority_message": result.get("authority_message") or "",
                "error_code": "ambiguous_event" if result.get("ambiguous") else "" if result.get("accepted") else "event_rejected",
                "error_message": "SIFEN event requires manual reconciliation." if result.get("ambiguous") else "",
                "error_type": "sifen_event", "metadata_json": metadata,
            })
        else:
            common.update({
                "authority_code": result.get("authority_code") or "", "authority_message": result.get("authority_message") or "",
                "authority_protocol": result.get("authority_protocol") or "", "authority_timestamp": result.get("authority_timestamp") or "",
                "metadata_json": metadata,
            })
        record.write(common)

    def _failure(self, category, message, ambiguous):
        return {"ok": False, "accepted": False, "ambiguous": ambiguous, "category": category, "http_status": 0, "response_hash": "", "authority_code": "", "authority_message": message, "authority_protocol": "", "authority_timestamp": ""}

    def _next_id(self, adapter, max_length):
        value = adapter.sequence_id.next_by_id() if adapter.sequence_id else ""
        if not value or not value.isdigit() or len(value) > max_length:
            raise ValidationError("SIFEN event requires a valid persistent numeric identifier.")
        return value

    def _safe_endpoint(self, value):
        parsed = urlsplit(value or "")
        return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", "")) if parsed.scheme == "https" and parsed.hostname else ""

    def _value(self, node, name):
        child = node.find(self._tag(name)) if node is not None else None
        return (child.text or "").strip() if child is not None else ""

    def _text(self, parent, name, value):
        etree.SubElement(parent, self._tag(name)).text = str(value)

    def _tag(self, name):
        return f"{{{self.SIFEN_NS}}}{name}"

    def _soap_tag(self, name):
        return f"{{{self.SOAP_NS}}}{name}"


class PySifenCancellationService:
    def __init__(self, env, *, event_service=None):
        self.env = env
        self.event_service = event_service or PySifenEventService(env)

    def cancel(self, *, document, reason, signing_timestamp=None):
        document.ensure_one()
        self._lock(document)
        existing = self._existing(document)
        if document.state == "cancelled" and existing:
            return {"accepted": True, "transmission_id": existing.id, "idempotent": True}
        if self._unresolved(document):
            raise ValidationError(
                "SIFEN cancellation has an unresolved prior attempt requiring manual review."
            )
        self._validate(document, reason)
        adapter = document.adapter_config_id
        event_id = self.event_service._next_id(adapter, 10)
        transmission = self.env["fiscal.transmission"].sudo().create({
            "document_id": document.id, "transmission_type": "cancel", "state": "pending",
            "country_code": "PY", "environment": document.environment,
            "country_identifier": document.country_identifier or document.py_cdc,
            "attempt_number": len(document.transmission_ids.filtered(lambda tx: tx.transmission_type == "cancel")) + 1,
            "started_at": fields.Datetime.now(),
        })
        event_xml = self.event_service.build_cancellation_event(
            event_id=event_id, cdc=document.country_identifier or document.py_cdc,
            reason=reason.strip(), signing_timestamp=signing_timestamp or fields.Datetime.now(),
        )
        accepted_before = document.transmission_ids.filtered(lambda tx: tx.transmission_type == "submit" and tx.state == "accepted").ids
        result = self.event_service.execute(adapter=adapter, event_xml_bytes=event_xml, audit_record=transmission, audit_model="fiscal.transmission", original_ids=accepted_before)
        if result.get("accepted"):
            document.with_context(einvoice_skip_fiscal_document_lock=True).write({"state": "cancelled", "cancelled_at": fields.Datetime.now()})
            self.env["fiscal.event"].sudo().create({
                "document_id": document.id, "event_type": "sifen_cancellation", "from_state": "accepted", "to_state": "cancelled",
                "message": result.get("authority_message") or "SIFEN cancellation accepted.",
                "payload_hash": transmission.request_hash,
                "metadata_json": json.dumps({"transmission_id": transmission.id, "authority_code": result.get("authority_code"), "authority_protocol": result.get("authority_protocol"), "authority_timestamp": result.get("authority_timestamp")}, sort_keys=True),
            })
        return dict(result, transmission_id=transmission.id, event_id=event_id)

    def _validate(self, document, reason):
        if document.state != "accepted":
            raise ValidationError("Only an accepted Paraguay fiscal document can be cancelled.")
        if not document.accepted_at:
            raise ValidationError("SIFEN cancellation requires the authority acceptance timestamp.")
        if not isinstance(reason, str) or not 5 <= len(reason.strip()) <= 500:
            raise ValidationError("SIFEN cancellation reason must contain 5 to 500 characters.")
        hours = 48 if document.document_type == "invoice" else 168
        if fields.Datetime.now() > document.accepted_at + timedelta(hours=hours):
            raise ValidationError("SIFEN cancellation eligibility window has expired.")
        if not (document.country_identifier or document.py_cdc):
            raise ValidationError("SIFEN cancellation requires the accepted document CDC.")

    def _existing(self, document):
        return self.env["fiscal.transmission"].sudo().search([("document_id", "=", document.id), ("transmission_type", "=", "cancel"), ("state", "=", "accepted")], limit=1)

    def _unresolved(self, document):
        return self.env["fiscal.transmission"].sudo().search_count([
            ("document_id", "=", document.id),
            ("transmission_type", "=", "cancel"),
            ("state", "in", ["pending", "sent", "manual_review"]),
        ])

    def _lock(self, document):
        self.env.cr.execute("SELECT id FROM fiscal_document WHERE id = %s FOR UPDATE", [document.id])


class PySifenInutilizationService:
    TYPE_CODES = {"invoice": "1", "credit_note": "5", "debit_note": "6"}

    def __init__(self, env, *, event_service=None):
        self.env = env
        self.event_service = event_service or PySifenEventService(env)

    def inutilize(self, *, adapter, timbrado, establishment, point_of_issue, document_type, number_from, number_to, reason, occurred_on, signing_timestamp=None):
        self._lock_scope(timbrado)
        existing = self._exact(adapter, timbrado, establishment, point_of_issue, document_type, number_from, number_to)
        if existing:
            return {"accepted": existing.state == "accepted", "inutilization_id": existing.id, "idempotent": True}
        self._validate_scope(adapter, timbrado, establishment, point_of_issue, document_type, number_from, number_to, reason, occurred_on)
        record = self.env["fiscal.py.inutilization"].sudo().create({
            "tenant_id": adapter.tenant_id.id, "company_id": adapter.company_id.id, "environment": adapter.environment,
            "adapter_config_id": adapter.id, "timbrado_id": timbrado.id, "establishment_id": establishment.id,
            "point_of_issue_id": point_of_issue.id, "document_type": document_type,
            "number_from": number_from, "number_to": number_to, "reason": reason.strip(), "state": "pending",
        })
        event_id = self.event_service._next_id(adapter, 10)
        record.event_id = event_id
        event_xml = self.event_service.build_inutilization_event(
            event_id=event_id, timbrado=timbrado.number, establishment=establishment.code, point=point_of_issue.code,
            number_from=number_from, number_to=number_to, document_type_code=self.TYPE_CODES[document_type],
            reason=reason.strip(), signing_timestamp=signing_timestamp or fields.Datetime.now(),
        )
        result = self.event_service.execute(adapter=adapter, event_xml_bytes=event_xml, audit_record=record, audit_model="fiscal.py.inutilization")
        return dict(result, inutilization_id=record.id, event_id=event_id)

    def _validate_scope(self, adapter, timbrado, establishment, point, document_type, start, end, reason, occurred_on):
        records = (timbrado, establishment, point)
        if any(rec.tenant_id != adapter.tenant_id or rec.company_id != adapter.company_id for rec in records):
            raise ValidationError("Paraguay inutilization fiscal scope is invalid.")
        if any(getattr(rec, "environment", adapter.environment) != adapter.environment for rec in records):
            raise ValidationError("Paraguay inutilization environment scope is invalid.")
        if document_type not in self.TYPE_CODES or timbrado.document_type != document_type:
            raise ValidationError("Paraguay inutilization document type is invalid.")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start or end > 9999999 or end - start + 1 > 1000:
            raise ValidationError("SIFEN inutilization requires a valid range of at most 1000 numbers.")
        if not isinstance(reason, str) or not 5 <= len(reason.strip()) <= 150:
            raise ValidationError("SIFEN inutilization reason must contain 5 to 150 characters.")
        occurred = fields.Date.to_date(occurred_on)
        if not occurred:
            raise ValidationError("SIFEN inutilization occurrence date is required.")
        next_month = (occurred.replace(day=28) + timedelta(days=4)).replace(day=1)
        deadline = next_month.replace(day=15)
        today = datetime.now(timezone.utc).astimezone(
            PySifenDatetimeService.PARAGUAY_TIMEZONE
        ).date()
        if occurred > today:
            raise ValidationError("SIFEN inutilization occurrence date cannot be in the future.")
        if today > deadline:
            raise ValidationError("SIFEN inutilization reporting deadline has expired.")
        issued = self.env["fiscal.document"].sudo().search_count([
            ("tenant_id", "=", adapter.tenant_id.id), ("company_id", "=", adapter.company_id.id),
            ("environment", "=", adapter.environment), ("py_timbrado_id", "=", timbrado.id),
            ("py_establishment_id", "=", establishment.id), ("py_point_of_issue_id", "=", point.id),
            ("document_type", "=", document_type), ("py_document_number", ">=", str(start).zfill(7)),
            ("py_document_number", "<=", str(end).zfill(7)),
        ])
        if issued:
            raise ValidationError("SIFEN inutilization range overlaps an issued fiscal number.")
        overlap = self.env["fiscal.py.inutilization"].sudo().search_count([
            ("tenant_id", "=", adapter.tenant_id.id), ("company_id", "=", adapter.company_id.id),
            ("environment", "=", adapter.environment), ("timbrado_id", "=", timbrado.id),
            ("establishment_id", "=", establishment.id), ("point_of_issue_id", "=", point.id),
            ("document_type", "=", document_type), ("number_from", "<=", end), ("number_to", ">=", start),
        ])
        if overlap:
            raise ValidationError("SIFEN inutilization range overlaps existing evidence.")

    def _exact(self, adapter, timbrado, establishment, point, document_type, start, end):
        return self.env["fiscal.py.inutilization"].sudo().search([
            ("tenant_id", "=", adapter.tenant_id.id), ("company_id", "=", adapter.company_id.id),
            ("environment", "=", adapter.environment), ("timbrado_id", "=", timbrado.id),
            ("establishment_id", "=", establishment.id), ("point_of_issue_id", "=", point.id),
            ("document_type", "=", document_type), ("number_from", "=", start), ("number_to", "=", end),
        ], limit=1)

    def _lock_scope(self, timbrado):
        self.env.cr.execute("SELECT id FROM fiscal_py_timbrado WHERE id = %s FOR UPDATE", [timbrado.id])
