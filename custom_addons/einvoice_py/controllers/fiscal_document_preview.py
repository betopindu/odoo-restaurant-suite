from odoo import http
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.http import content_disposition, request

from odoo.addons.einvoice_py.services.py_kude_preview_service import (
    PyKudePreviewService,
)


class PyFiscalDocumentPreviewController(http.Controller):
    @http.route(
        "/einvoice_py/preview/<string:document_uuid>/kude",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def preview(self, document_uuid, **_kwargs):
        document = request.env["fiscal.document"].search([
            ("uuid", "=", document_uuid),
        ], limit=1)
        if not document:
            return request.not_found()
        try:
            result = PyKudePreviewService(request.env).render(document=document)
        except (AccessError, MissingError, ValidationError):
            return request.not_found()
        return request.make_response(
            result.pdf_bytes,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Disposition", content_disposition(result.filename)),
                ("X-Content-Type-Options", "nosniff"),
                ("Cache-Control", "private, no-store"),
            ],
        )
