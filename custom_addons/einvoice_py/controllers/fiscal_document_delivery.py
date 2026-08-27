from odoo import http
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.http import content_disposition, request

from odoo.addons.einvoice_py.services.py_fiscal_document_delivery_service import (
    PyFiscalDocumentDeliveryService,
)


class PyFiscalDocumentDeliveryController(http.Controller):
    @http.route(
        "/einvoice_py/delivery/<string:document_uuid>/<string:file_kind>",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def download(self, document_uuid, file_kind, **_kwargs):
        if file_kind not in ("pdf", "xml"):
            return request.not_found()
        document = request.env["fiscal.document"].search([
            ("uuid", "=", document_uuid),
        ], limit=1)
        if not document:
            return request.not_found()
        try:
            delivery_file = PyFiscalDocumentDeliveryService(request.env).resolve_file(
                document=document,
                file_kind=file_kind,
            )
        except (AccessError, MissingError, ValidationError):
            return request.not_found()
        return request.make_response(
            delivery_file.content,
            headers=[
                ("Content-Type", delivery_file.mimetype),
                ("Content-Disposition", content_disposition(delivery_file.filename)),
                ("X-Content-Type-Options", "nosniff"),
                ("Cache-Control", "private, no-store"),
            ],
        )
