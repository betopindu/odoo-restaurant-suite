from odoo import fields, http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.fiscal_api.services.authentication import FiscalApiAuthenticationService
from odoo.addons.fiscal_api.services.document_mapper import (
    FiscalApiDocumentMapper,
    FiscalApiPayloadError,
)


class FiscalDocumentApiController(http.Controller):
    SUPPORTED_PROCESSING_MODES = {"async", "sync"}
    SYNC_TERMINAL_STATES = {"accepted", "rejected", "failed_final", "manual_review"}

    def _error_response(self, code, message, details=None, status=400):
        return request.make_json_response(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details or [],
                },
            },
            status=status,
        )

    def _raw_bearer_key(self):
        authorization = request.httprequest.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return False
        raw_key = authorization[len("Bearer "):].strip()
        return raw_key or False

    def _authenticate_request(self):
        authentication = FiscalApiAuthenticationService(request.env)
        return authentication.authenticate(self._raw_bearer_key())

    def _serialize_datetime(self, value):
        return fields.Datetime.to_string(value) if value else None

    def _status_url(self, document):
        return f"/api/v1/fiscal/documents/{document.uuid}"

    def _sync_response(self, document):
        if document.state in self.SYNC_TERMINAL_STATES:
            return request.make_json_response(
                {
                    "data": {
                        "uuid": document.uuid,
                        "state": document.state,
                        "processing_mode": "sync",
                        "country_identifier": document.country_identifier,
                        "authority_status": document.authority_status,
                        "authority_receipt_ref": document.authority_receipt_ref,
                        "status_url": self._status_url(document),
                    },
                },
                status=201,
            )
        return request.make_json_response(
            {
                "data": {
                    "uuid": document.uuid,
                    "state": document.state,
                    "processing_mode": "sync_timeout_async_continuation",
                    "message": "Processing continues asynchronously.",
                    "status_url": self._status_url(document),
                },
            },
            status=202,
        )

    @http.route(
        "/api/v1/fiscal/documents",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def create_fiscal_document(self, **kwargs):
        api_key, key_status = self._authenticate_request()
        if key_status == "invalid":
            return self._error_response(
                "invalid_api_key",
                "The API key is invalid.",
                status=401,
            )
        if key_status != "valid":
            return self._error_response(
                "api_key_unavailable",
                "The API key is inactive, revoked, or expired.",
                status=403,
            )

        if not request.httprequest.is_json:
            return self._error_response(
                "malformed_request",
                "Request body must be JSON.",
                status=400,
            )
        payload = request.httprequest.get_json(silent=True)
        if not isinstance(payload, dict):
            return self._error_response(
                "malformed_request",
                "Request body must be a JSON object.",
                status=400,
            )

        processing_mode = payload.get(
            "processing_mode",
            api_key.default_processing_mode or "async",
        )
        if processing_mode not in self.SUPPORTED_PROCESSING_MODES:
            return self._error_response(
                "unsupported_processing_mode",
                "The requested processing mode is not supported.",
                ["processing_mode must be async or sync."],
                status=422,
            )

        try:
            with request.env.cr.savepoint():
                mapper = FiscalApiDocumentMapper(
                    request.env,
                    api_key,
                )
                document, _existing = mapper.create_or_get_document(payload)
                if processing_mode == "sync":
                    mapper.process_immediately(document)
        except FiscalApiPayloadError as error:
            return self._error_response(
                "validation_error",
                "Invalid fiscal document payload.",
                error.details,
                status=422,
            )
        except ValidationError as error:
            return self._error_response(
                "validation_error",
                str(error),
                status=422,
            )
        except Exception:
            return self._error_response(
                "internal_error",
                "Unexpected server error.",
                status=500,
            )

        api_key.sudo().write({"last_used_at": fields.Datetime.now()})
        if processing_mode == "sync":
            return self._sync_response(document)
        return request.make_json_response(
            {
                "data": {
                    "uuid": document.uuid,
                    "state": document.state,
                    "processing_mode": "async",
                    "idempotency_key": document.idempotency_key,
                    "status_url": self._status_url(document),
                },
            },
            status=202,
        )

    @http.route(
        "/api/v1/fiscal/documents/<string:document_uuid>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def get_fiscal_document_status(self, document_uuid, **kwargs):
        api_key, key_status = self._authenticate_request()
        if key_status == "invalid":
            return self._error_response(
                "invalid_api_key",
                "The API key is invalid.",
                status=401,
            )
        if key_status != "valid":
            return self._error_response(
                "api_key_unavailable",
                "The API key is inactive, revoked, or expired.",
                status=403,
            )

        try:
            document = request.env["fiscal.document"].sudo().search(
                [
                    ("uuid", "=", document_uuid),
                    ("tenant_id", "=", api_key.tenant_id.id),
                ],
                limit=1,
            )
            if not document:
                return self._error_response(
                    "document_not_found",
                    "Fiscal document not found.",
                    status=404,
                )

            api_key.sudo().write({"last_used_at": fields.Datetime.now()})
            return request.make_json_response({
                "data": {
                    "uuid": document.uuid,
                    "document_type": document.document_type,
                    "state": document.state,
                    "country_code": document.country_code,
                    "environment": document.environment,
                    "source_reference": document.source_reference,
                    "idempotency_key": document.idempotency_key,
                    "country_identifier": document.country_identifier,
                    "authority_status": document.authority_status,
                    "authority_receipt_ref": document.authority_receipt_ref,
                    "submitted_at": self._serialize_datetime(document.submitted_at),
                    "accepted_at": self._serialize_datetime(document.accepted_at),
                    "rejected_at": self._serialize_datetime(document.rejected_at),
                    "cancelled_at": self._serialize_datetime(document.cancelled_at),
                },
            })
        except Exception:
            return self._error_response(
                "internal_error",
                "Unexpected server error.",
                status=500,
            )
