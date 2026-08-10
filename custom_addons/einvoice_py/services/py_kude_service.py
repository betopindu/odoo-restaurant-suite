import base64
import hashlib
import io
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_qr_payload_attachment_service import (
    PyQrPayloadAttachmentService,
)


@dataclass(frozen=True, slots=True)
class PyKudeResult:
    pdf_bytes: bytes = field(repr=False)
    attachment_id: int
    payload_attachment_id: int
    qr_attachment_id: int
    sha256: str
    page_count: int
    cdc: str
    logo_rendered: bool


class PyKudeService:
    """Build and version a Paraguay KuDE solely from persisted artifacts."""

    PAYLOAD_TYPE = "paraguay_payload_json"
    ATTACHMENT_TYPE = "paraguay_kude_pdf"
    ITEMS_PER_PAGE = 18
    PAGE_SIZE = A4
    MARGIN = 15 * mm
    QR_SIZE = 28 * mm

    def __init__(self, env, qr_attachment_service=None):
        self.env = env
        self.qr_attachment_service = (
            qr_attachment_service
            if qr_attachment_service is not None
            else PyQrPayloadAttachmentService(env)
        )

    def generate(self, *, document, filename=None):
        document.ensure_one()
        self._validate_document(document)
        payload_attachment, payload = self.load_payload(document)
        qr_attachment, qr_payload = self.qr_attachment_service.read_current(
            document=document
        )
        self.validate_payload(payload, document)
        logo_bytes = self.load_company_logo(document)
        pdf_bytes, page_count = self.render_pdf(
            payload,
            qr_payload=qr_payload,
            logo_bytes=logo_bytes,
        )
        attachment = self._persist(
            document=document,
            pdf_bytes=pdf_bytes,
            filename=filename or f"{document.uuid}-kude.pdf",
            metadata={
                "cdc": payload["cdc"],
                "page_count": page_count,
                "payload_attachment_id": payload_attachment.id,
                "payload_sha256": payload_attachment.sha256,
                "qr_attachment_id": qr_attachment.id,
                "qr_payload_sha256": qr_attachment.sha256,
            },
        )
        return PyKudeResult(
            pdf_bytes=pdf_bytes,
            attachment_id=attachment.id,
            payload_attachment_id=payload_attachment.id,
            qr_attachment_id=qr_attachment.id,
            sha256=attachment.sha256,
            page_count=page_count,
            cdc=payload["cdc"],
            logo_rendered=bool(logo_bytes),
        )

    def current(self, *, document):
        document.ensure_one()
        attachments = self._attachments(document)
        current = attachments.filtered(
            lambda item: self._metadata(item).get("artifact_status") == "current"
        )[:1]
        return current or attachments[:1]

    def _validate_document(self, document):
        if (document.country_code or "").upper() != "PY":
            raise ValidationError("KuDE requires a Paraguay fiscal document.")
        if document.document_type != "invoice":
            raise ValidationError(
                "KuDE currently supports Paraguay electronic invoices only."
            )

    def load_payload(self, document):
        attachment = self.env["fiscal.attachment"].sudo().search(
            [
                ("document_id", "=", document.id),
                ("attachment_type", "=", self.PAYLOAD_TYPE),
            ],
            order="id desc",
            limit=1,
        )
        if not attachment or not attachment.ir_attachment_id:
            raise ValidationError("Persisted Paraguay payload is missing for KuDE.")
        try:
            content = base64.b64decode(
                attachment.ir_attachment_id.datas or b"",
                validate=True,
            )
            payload = json.loads(content.decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            raise ValidationError("Persisted Paraguay payload is invalid for KuDE.") from None
        if hashlib.sha256(content).hexdigest() != attachment.sha256:
            raise ValidationError("Persisted Paraguay payload integrity check failed.")
        if not isinstance(payload, dict):
            raise ValidationError("Persisted Paraguay payload is invalid for KuDE.")
        return attachment, payload

    def validate_payload(self, payload, document):
        required_sections = (
            "document",
            "operation",
            "issuer",
            "receiver",
            "condition",
            "items",
            "totals",
        )
        if payload.get("version") != "150" or any(
            not isinstance(payload.get(section), dict)
            for section in required_sections
            if section != "items"
        ) or not isinstance(payload.get("items"), list):
            raise ValidationError("Persisted Paraguay payload is incomplete for KuDE.")
        if payload.get("environment") not in ("test", "production"):
            raise ValidationError(
                "Persisted Paraguay payload environment is invalid for KuDE."
            )
        cdc = payload.get("cdc")
        if (
            not isinstance(cdc, str)
            or len(cdc) != 44
            or not cdc.isdigit()
            or cdc != (document.py_cdc or document.country_identifier)
        ):
            raise ValidationError("Persisted Paraguay payload CDC is invalid for KuDE.")
        mandatory = (
            payload["document"].get("py_full_number"),
            payload["document"].get("issue_datetime"),
            payload["issuer"].get("name"),
            payload["issuer"].get("full_ruc"),
            payload["issuer"].get("timbrado_number"),
            payload["receiver"].get("name"),
            payload["condition"].get("sale_condition_description"),
            payload["operation"].get("currency"),
        )
        if not payload["items"] or any(value in (None, "") for value in mandatory):
            raise ValidationError("Persisted Paraguay payload is incomplete for KuDE.")

    def load_company_logo(self, document):
        encoded = document.company_id.logo
        if not encoded:
            return None
        try:
            logo_bytes = base64.b64decode(encoded, validate=True)
            ImageReader(io.BytesIO(logo_bytes)).getSize()
        except Exception:
            return None
        return logo_bytes

    def render_pdf(
        self,
        payload,
        *,
        qr_payload=None,
        preview=False,
        logo_bytes=None,
    ):
        if not preview and not qr_payload:
            raise ValidationError("Final KuDE rendering requires the persisted fiscal QR.")
        pages = self._paginate_items(payload["items"])
        page_count = len(pages)
        output = io.BytesIO()
        pdf = canvas.Canvas(
            output,
            pagesize=self.PAGE_SIZE,
            invariant=1,
            pageCompression=1,
        )
        pdf.setTitle(
            "Preview de Factura Electronica"
            if preview
            else "KuDE de Factura Electronica"
        )
        pdf.setAuthor("Fiscal e-Invoice Platform")
        for page_index, page_items in enumerate(pages):
            y = self._draw_document_header(
                pdf,
                payload,
                page_index,
                page_count,
                preview=preview,
                logo_bytes=logo_bytes,
            )
            y = self._draw_operation_block(pdf, payload, y)
            y = self._draw_item_table(pdf, page_items, y)
            if page_index == page_count - 1:
                y = self._draw_totals_table(pdf, payload, y)
                if preview:
                    self._draw_fiscal_footer(pdf, payload, y - 3 * mm, preview=True)
                else:
                    self._draw_fiscal_footer(
                        pdf,
                        payload,
                        y - 3 * mm,
                        qr_payload=qr_payload,
                    )
            pdf.showPage()
        pdf.save()
        return output.getvalue(), page_count

    def _draw_document_header(
        self,
        pdf,
        payload,
        page_index,
        page_count,
        *,
        preview=False,
        logo_bytes=None,
    ):
        width, height = self.PAGE_SIZE
        issuer = payload["issuer"]
        document = payload["document"]
        top = height - self.MARGIN
        content_width = width - 2 * self.MARGIN
        header_height = 33 * mm
        bottom = top - header_height
        divider = self.MARGIN + content_width * 0.62
        pdf.setLineWidth(0.7)
        pdf.rect(self.MARGIN, bottom, content_width, header_height)
        pdf.line(divider, bottom, divider, top)

        text_x = self.MARGIN + 4 * mm
        if logo_bytes:
            logo_width = 28 * mm
            logo_height = 12 * mm
            self._draw_logo(
                pdf,
                logo_bytes,
                self.MARGIN + 3 * mm,
                top - logo_height - 3 * mm,
                logo_width,
                logo_height,
            )
            text_x += logo_width + 3 * mm
        y = top - 5 * mm
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(text_x, y, self._safe(issuer.get("name")))
        trade_name = issuer.get("branch_name")
        if trade_name and self._safe(trade_name).casefold() != self._safe(
            issuer.get("name")
        ).casefold():
            y -= 9
            pdf.setFont("Helvetica-Bold", 7)
            pdf.drawString(text_x, y, self._safe(trade_name))

        details_x = self.MARGIN + 4 * mm
        y = top - 18 * mm
        pdf.setFont("Helvetica", 6.5)
        activity = "; ".join(
            self._safe(item.get("description"))
            for item in issuer.get("economic_activities") or []
            if item.get("description")
        )
        for label, value in (
            ("Direccion", self._joined(issuer.get("address"), issuer.get("city_name"))),
            ("Telefono", issuer.get("phone")),
            ("Correo", issuer.get("email")),
            ("Actividad", activity),
        ):
            if value not in (None, ""):
                line = f"{label}: {self._safe(value)}"
                pdf.drawString(details_x, y, self._truncate(line, 88))
                y -= 8

        right_x = divider + 4 * mm
        right_width = width - self.MARGIN - right_x - 3 * mm
        y = top - 5 * mm
        pdf.setFont("Helvetica-Bold", 8)
        for label, value in (
            ("RUC", issuer.get("full_ruc")),
            ("Timbrado Nro.", issuer.get("timbrado_number")),
            ("Inicio de vigencia", issuer.get("timbrado_valid_from")),
        ):
            pdf.drawString(right_x, y, self._truncate(f"{label}: {self._safe(value)}", 42))
            y -= 10
        y -= 2
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawCentredString(right_x + right_width / 2, y, "FACTURA ELECTRONICA")
        y -= 13
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawCentredString(
            right_x + right_width / 2,
            y,
            self._safe(document.get("py_full_number")),
        )
        y -= 11
        pdf.setFont("Helvetica", 6.5)
        pdf.drawRightString(
            right_x + right_width,
            y,
            f"Pagina {page_index + 1} de {page_count}",
        )

        y = bottom - 3 * mm
        if preview:
            bar_height = 9 * mm
            pdf.setFillGray(0.92)
            pdf.rect(self.MARGIN, y - bar_height, content_width, bar_height, fill=1)
            pdf.setFillGray(0)
            pdf.setFont("Helvetica-Bold", 11)
            pdf.drawCentredString(
                width / 2,
                y - 4 * mm,
                "VISTA PREVIA - SIN VALIDEZ FISCAL",
            )
            pdf.setFont("Helvetica-Bold", 7)
            pdf.drawRightString(
                width - self.MARGIN - 3 * mm,
                y - 7 * mm,
                f"AMBIENTE: {payload['environment'].upper()}",
            )
            return y - bar_height - 3 * mm
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawRightString(
            width - self.MARGIN,
            y,
            f"AMBIENTE: {payload['environment'].upper()}",
        )
        return y - 3 * mm

    def _draw_operation_block(self, pdf, payload, top):
        width, _height = self.PAGE_SIZE
        receiver = payload["receiver"]
        operation = payload["operation"]
        condition = payload["condition"]
        document = payload["document"]
        left = (
            ("Fecha y hora de emision", document.get("issue_datetime")),
            ("Condicion de venta", condition.get("sale_condition_description")),
            ("Moneda", operation.get("currency_description") or operation.get("currency")),
            ("Tipo de cambio", operation.get("exchange_rate")),
            ("Tipo de operacion", operation.get("transaction_type_description")),
        )
        receiver_id = self._receiver_id(receiver)
        right = (
            ("RUC/Documento", receiver_id),
            ("Nombre o razon social", receiver.get("name")),
            ("Direccion", receiver.get("address")),
            ("Telefono", receiver.get("phone")),
            ("Correo electronico", receiver.get("email")),
        )
        installments = condition.get("installments") or []
        left_count = sum(value not in (None, "") for _label, value in left)
        right_count = sum(value not in (None, "") for _label, value in right)
        installment_height = 9 if any(item.get("due_date") for item in installments) else 0
        block_height = max(48, max(left_count, right_count) * 9 + 12 + installment_height)
        bottom = top - block_height
        content_width = width - 2 * self.MARGIN
        divider = self.MARGIN + content_width / 2
        pdf.rect(self.MARGIN, bottom, content_width, block_height)
        pdf.line(divider, bottom, divider, top)
        self._draw_label_values(pdf, left, self.MARGIN + 3 * mm, top - 5 * mm, 78)
        self._draw_label_values(pdf, right, divider + 3 * mm, top - 5 * mm, 70)
        if installments:
            due_dates = ", ".join(
                self._safe(item.get("due_date"))
                for item in installments
                if item.get("due_date")
            )
            if due_dates:
                pdf.setFont("Helvetica", 6.5)
                pdf.drawString(
                    self.MARGIN + 3 * mm,
                    bottom + 3 * mm,
                    self._truncate(f"Cuotas / vencimientos: {due_dates}", 82),
                )
        return bottom - 3 * mm

    def _item_columns(self):
        return (
            ("Codigo", 14 * mm, "left"),
            ("Descripcion", 54 * mm, "left"),
            ("Unidad", 10 * mm, "left"),
            ("Cantidad", 12 * mm, "right"),
            ("Precio unit.", 21 * mm, "right"),
            ("Descuento", 15 * mm, "right"),
            ("Exentas", 17 * mm, "right"),
            ("IVA 5%", 17 * mm, "right"),
            ("IVA 10%", 20 * mm, "right"),
        )

    def _draw_item_table(self, pdf, items, top):
        columns = self._item_columns()
        table_width = sum(item[1] for item in columns)
        first_header = 12
        second_header = 15
        header_height = first_header + second_header
        y = top
        pdf.setFillGray(0.92)
        pdf.rect(self.MARGIN, y - header_height, table_width, header_height, fill=1)
        pdf.setFillGray(0)
        sales_x = self.MARGIN + sum(item[1] for item in columns[:6])
        pdf.line(sales_x, y - first_header, self.MARGIN + table_width, y - first_header)
        pdf.setFont("Helvetica-Bold", 6.2)
        pdf.drawCentredString(
            sales_x + sum(item[1] for item in columns[6:]) / 2,
            y - 8,
            "VALOR DE VENTA",
        )
        x = self.MARGIN
        for index, (label, column_width, _alignment) in enumerate(columns):
            label_y = y - 21 if index >= 6 else y - 17
            pdf.drawCentredString(x + column_width / 2, label_y, label)
            x += column_width
        y -= header_height
        for item in items:
            description_lines = self._wrap_text(
                item.get("description"),
                51 * mm,
                "Helvetica",
                6,
            )
            row_height = max(18, 8 + len(description_lines) * 8)
            rate = self._decimal(item.get("tax_rate"))
            affectation = item.get("tax_affectation")
            total = item.get("total")
            values = (
                item.get("code"),
                description_lines,
                item.get("unit_measure_description"),
                self._format_quantity(item.get("quantity")),
                self._format_amount(item.get("price_unit")),
                self._format_amount(item.get("discount")),
                self._format_amount(total) if affectation == "3" else "",
                self._format_amount(total) if affectation != "3" and rate == Decimal("5") else "",
                self._format_amount(total) if affectation != "3" and rate == Decimal("10") else "",
            )
            x = self.MARGIN
            pdf.setFont("Helvetica", 6)
            for value, (_label, column_width, alignment) in zip(values, columns):
                if isinstance(value, list):
                    for line_index, line in enumerate(value):
                        pdf.drawString(x + 2, y - 9 - line_index * 8, line)
                elif alignment == "right":
                    pdf.drawRightString(x + column_width - 2, y - 11, self._safe(value))
                else:
                    pdf.drawString(x + 2, y - 11, self._safe(value))
                x += column_width
            pdf.rect(self.MARGIN, y - row_height, table_width, row_height)
            x = self.MARGIN
            for _label, column_width, _alignment in columns[:-1]:
                x += column_width
                pdf.line(x, y - row_height, x, y)
            y -= row_height
        return y

    def _paginate_items(self, items):
        pages = []
        current = []
        used_height = 0
        for item in items:
            lines = len(
                self._wrap_text(
                    item.get("description"),
                    51 * mm,
                    "Helvetica",
                    6,
                )
            )
            row_height = max(18, 8 + lines * 8)
            if current and used_height + row_height > 285:
                pages.append(current)
                current = []
                used_height = 0
            current.append(item)
            used_height += row_height
        pages.append(current)
        return pages

    def _draw_totals_table(self, pdf, payload, top):
        width, _height = self.PAGE_SIZE
        totals = payload["totals"]
        rows = (
            ("SUBTOTAL EXENTAS", totals.get("subtotal_exempt")),
            ("SUBTOTAL IVA 5%", totals.get("subtotal_5")),
            ("SUBTOTAL IVA 10%", totals.get("subtotal_10")),
            ("TOTAL DE LA OPERACION", totals.get("total_operation")),
            ("TOTAL A PAGAR", totals.get("total_general")),
            ("TOTAL EN GUARANIES", totals.get("total_general")),
            ("LIQUIDACION IVA 5%", totals.get("total_vat_5")),
            ("LIQUIDACION IVA 10%", totals.get("total_vat_10")),
            ("TOTAL IVA", totals.get("total_vat")),
        )
        table_width = 92 * mm
        row_height = 10
        x = width - self.MARGIN - table_width
        y = top
        pdf.setFont("Helvetica-Bold", 6.5)
        for label, value in rows:
            pdf.rect(x, y - row_height, table_width, row_height)
            pdf.line(x + 62 * mm, y - row_height, x + 62 * mm, y)
            pdf.drawString(x + 3, y - 7, label)
            pdf.drawRightString(
                x + table_width - 3,
                y - 7,
                self._format_amount(value),
            )
            y -= row_height
        return y

    def _draw_fiscal_footer(
        self,
        pdf,
        payload,
        top,
        *,
        qr_payload=None,
        preview=False,
    ):
        width, _height = self.PAGE_SIZE
        block_x = self.MARGIN
        block_width = width - 2 * self.MARGIN
        block_height = 34 * mm
        block_y = top - block_height
        if block_y < self.MARGIN:
            raise ValidationError("KuDE content exceeds the printable page area.")
        qr_box = 34 * mm
        pdf.rect(block_x, block_y, block_width, block_height)
        pdf.line(block_x + qr_box, block_y, block_x + qr_box, block_y + block_height)
        qr_x = block_x + 3 * mm
        qr_y = block_y + 3 * mm
        if preview:
            pdf.rect(qr_x, qr_y, self.QR_SIZE, self.QR_SIZE)
            pdf.setFont("Helvetica-Bold", 7)
            pdf.drawCentredString(
                qr_x + self.QR_SIZE / 2,
                qr_y + self.QR_SIZE / 2 + 4,
                "QR NO DISPONIBLE",
            )
            pdf.setFont("Helvetica", 6)
            pdf.drawCentredString(
                qr_x + self.QR_SIZE / 2,
                qr_y + self.QR_SIZE / 2 - 6,
                "Vista previa no fiscal",
            )
        else:
            self._draw_qr_image(pdf, qr_payload, qr_x, qr_y)

        text_x = block_x + qr_box + 4 * mm
        text_width = block_width - qr_box - 8 * mm
        y = block_y + block_height - 5 * mm
        pdf.setFont("Helvetica", 6.5)
        if preview:
            lines = (
                "Vista previa para inspeccion interna.",
                "No constituye una representacion fiscal autorizada.",
                "El codigo QR fiscal no esta disponible.",
            )
        else:
            parsed = urlsplit(qr_payload)
            consultation_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            lines = (
                "Consulte la validez de esta Factura Electronica con el numero de CDC",
                f"impreso abajo en: {consultation_url}",
                f"CDC: {self._group_cdc(payload['cdc'])}",
            )
        for line in lines:
            pdf.drawString(text_x, y, self._truncate(line, 92))
            y -= 10
        pdf.setFont("Helvetica-Bold", 6.5)
        legal_lines = self._wrap_text(
            "ESTE DOCUMENTO ES UNA REPRESENTACION GRAFICA DE UN DOCUMENTO ELECTRONICO (XML)",
            text_width,
            "Helvetica-Bold",
            6.5,
        )
        for line in legal_lines:
            pdf.drawString(text_x, y, line)
            y -= 9

    def _draw_qr_image(self, pdf, qr_payload, x, y):
        qr = QrCodeWidget(qr_payload)
        bounds = qr.getBounds()
        drawing = Drawing(
            self.QR_SIZE,
            self.QR_SIZE,
            transform=[
                self.QR_SIZE / (bounds[2] - bounds[0]),
                0,
                0,
                self.QR_SIZE / (bounds[3] - bounds[1]),
                0,
                0,
            ],
        )
        drawing.add(qr)
        renderPDF.draw(
            drawing,
            pdf,
            x,
            y,
        )

    def _draw_logo(self, pdf, logo_bytes, x, y, max_width, max_height):
        image = ImageReader(io.BytesIO(logo_bytes))
        image_width, image_height = image.getSize()
        scale = min(max_width / image_width, max_height / image_height)
        width = image_width * scale
        height = image_height * scale
        pdf.drawImage(
            image,
            x + (max_width - width) / 2,
            y + (max_height - height) / 2,
            width=width,
            height=height,
            preserveAspectRatio=True,
            mask="auto",
        )

    def _draw_label_values(self, pdf, values, x, y, max_characters):
        pdf.setFont("Helvetica", 6.5)
        for label, value in values:
            if value in (None, ""):
                continue
            pdf.drawString(
                x,
                y,
                self._truncate(f"{label}: {self._safe(value)}", max_characters),
            )
            y -= 9

    def _truncate(self, value, length):
        text = self._safe(value)
        return text if len(text) <= length else f"{text[:length - 3]}..."

    def _format_amount(self, value):
        amount = self._decimal(value)
        if amount == amount.to_integral_value():
            return f"{int(amount):,}".replace(",", ".")
        return f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")

    def _format_quantity(self, value):
        quantity = self._decimal(value)
        if quantity == quantity.to_integral_value():
            return str(int(quantity))
        return format(quantity.normalize(), "f").replace(".", ",")

    def _persist(self, *, document, pdf_bytes, filename, metadata):
        self._lock_document(document)
        content_hash = hashlib.sha256(pdf_bytes).hexdigest()
        attachments = self._attachments(document)
        identical = attachments.filtered(lambda item: item.sha256 == content_hash)[:1]
        if identical:
            self._mark_current(identical, attachments - identical)
            return identical
        previous = attachments[:1]
        values = dict(metadata)
        values["artifact_status"] = "current"
        if previous:
            values["supersedes_attachment_id"] = previous.id
        ir_attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(pdf_bytes),
            "mimetype": "application/pdf",
            "res_model": "fiscal.document",
            "res_id": document.id,
        })
        attachment = self.env["fiscal.attachment"].sudo().create({
            "name": filename,
            "document_id": document.id,
            "attachment_type": self.ATTACHMENT_TYPE,
            "mimetype": "application/pdf",
            "filename": filename,
            "ir_attachment_id": ir_attachment.id,
            "sha256": content_hash,
            "is_sensitive": True,
            "metadata_json": self._metadata_json(values),
        })
        self._mark_superseded(attachments, attachment)
        return attachment

    def _attachments(self, document):
        return self.env["fiscal.attachment"].sudo().search(
            [
                ("document_id", "=", document.id),
                ("attachment_type", "=", self.ATTACHMENT_TYPE),
            ],
            order="id desc",
        )

    def _lock_document(self, document):
        self.env.cr.execute(
            "SELECT id FROM fiscal_document WHERE id = %s FOR UPDATE",
            [document.id],
        )
        if not self.env.cr.fetchone():
            raise ValidationError("Paraguay KuDE document no longer exists.")

    def _mark_current(self, current, superseded):
        metadata = self._metadata(current)
        metadata["artifact_status"] = "current"
        metadata.pop("superseded_by_attachment_id", None)
        current.write({"metadata_json": self._metadata_json(metadata)})
        self._mark_superseded(superseded, current)

    def _mark_superseded(self, attachments, current):
        for attachment in attachments:
            metadata = self._metadata(attachment)
            metadata["artifact_status"] = "superseded"
            metadata["superseded_by_attachment_id"] = current.id
            attachment.write({"metadata_json": self._metadata_json(metadata)})

    def _metadata(self, attachment):
        try:
            value = json.loads(attachment.metadata_json or "{}")
        except (TypeError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _metadata_json(self, metadata):
        allowed = (
            "artifact_status",
            "cdc",
            "page_count",
            "payload_attachment_id",
            "payload_sha256",
            "qr_attachment_id",
            "qr_payload_sha256",
            "superseded_by_attachment_id",
            "supersedes_attachment_id",
        )
        return json.dumps(
            {key: metadata[key] for key in allowed if metadata.get(key) not in (None, "")},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _receiver_id(self, receiver):
        if receiver.get("nature_code") == "1":
            return self._joined(
                receiver.get("ruc_or_document"),
                receiver.get("ruc_dv"),
                separator="-",
            )
        return receiver.get("id_number") or receiver.get("ruc_or_document")

    def _date_range(self, issuer):
        return self._joined(
            issuer.get("timbrado_valid_from"),
            issuer.get("timbrado_valid_to"),
            separator=" a ",
        )

    def _joined(self, first, second, separator=", "):
        return separator.join(
            self._safe(value)
            for value in (first, second)
            if value not in (None, "")
        )

    def _group_cdc(self, cdc):
        return " ".join(cdc[index:index + 4] for index in range(0, len(cdc), 4))

    def _decimal(self, value):
        try:
            return Decimal(str(value or 0))
        except (InvalidOperation, ValueError):
            raise ValidationError("Persisted Paraguay KuDE monetary value is invalid.") from None

    def _number(self, value):
        number = self._decimal(value)
        lexical = format(number, "f")
        if "." in lexical:
            lexical = lexical.rstrip("0").rstrip(".")
        whole, dot, fraction = lexical.partition(".")
        grouped = f"{int(whole):,}".replace(",", ".")
        return f"{grouped},{fraction}" if dot else grouped

    def _safe(self, value):
        return "" if value in (None, False) else str(value)

    def _wrap_text(self, value, width, font_name, font_size):
        words = self._safe(value).split()
        if not words:
            return [""]
        lines = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if stringWidth(candidate, font_name, font_size) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines
