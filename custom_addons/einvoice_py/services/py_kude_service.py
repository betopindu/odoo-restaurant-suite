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
        pdf_bytes, page_count = self.render_pdf(payload, qr_payload=qr_payload)
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

    def render_pdf(self, payload, *, qr_payload=None, preview=False):
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
            y = self._draw_header(
                pdf, payload, page_index, page_count, preview=preview
            )
            y = self._draw_items(pdf, page_items, y)
            if page_index == page_count - 1:
                self._draw_totals(pdf, payload, y)
            if page_index == 0:
                if preview:
                    self._draw_preview_placeholder(pdf)
                else:
                    self._draw_qr(pdf, payload["cdc"], qr_payload)
            if preview:
                self._draw_preview_mark(pdf)
            pdf.showPage()
        pdf.save()
        return output.getvalue(), page_count

    def _draw_header(self, pdf, payload, page_index, page_count, *, preview=False):
        width, height = self.PAGE_SIZE
        issuer = payload["issuer"]
        document = payload["document"]
        receiver = payload["receiver"]
        operation = payload["operation"]
        condition = payload["condition"]
        top = height - self.MARGIN
        pdf.setFont("Helvetica-Bold", 12)
        title = (
            "PREVIEW - SIN VALIDEZ FISCAL"
            if preview
            else "KuDE DE FACTURA ELECTRONICA"
        )
        pdf.drawString(self.MARGIN, top, title)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawCentredString(
            width / 2,
            top - 14,
            f"AMBIENTE: {payload['environment'].upper()}",
        )
        pdf.setFont("Helvetica", 7)
        pdf.drawRightString(width - self.MARGIN, top, f"Pagina {page_index + 1}/{page_count}")
        y = top - 25
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(self.MARGIN, y, self._safe(issuer.get("name")))
        y -= 10
        pdf.setFont("Helvetica", 7)
        activity = "; ".join(
            self._safe(item.get("description"))
            for item in issuer.get("economic_activities") or []
            if item.get("description")
        )
        for label, value in (
            ("Nombre de fantasia", issuer.get("branch_name")),
            ("Actividad", activity),
            ("Direccion", self._joined(issuer.get("address"), issuer.get("city_name"))),
            ("RUC", issuer.get("full_ruc")),
            ("Timbrado", issuer.get("timbrado_number")),
            ("Vigencia", self._date_range(issuer)),
            ("Factura Electronica", document.get("py_full_number")),
        ):
            pdf.drawString(self.MARGIN, y, f"{label}: {self._safe(value)}")
            y -= 9
        y -= 3
        pdf.line(self.MARGIN, y, width - self.MARGIN, y)
        y -= 11
        receiver_id = self._receiver_id(receiver)
        fields = (
            ("Fecha de emision", document.get("issue_datetime")),
            ("Condicion", condition.get("sale_condition_description")),
            ("Moneda", operation.get("currency_description") or operation.get("currency")),
            ("RUC/Documento", receiver_id),
            ("Receptor", receiver.get("name")),
            ("Direccion", receiver.get("address")),
            ("Telefono", receiver.get("phone")),
            ("Correo", receiver.get("email")),
            ("Tipo de operacion", operation.get("transaction_type_description")),
        )
        for label, value in fields:
            if value not in (None, ""):
                pdf.drawString(self.MARGIN, y, f"{label}: {self._safe(value)}")
                y -= 9
        installments = condition.get("installments") or []
        if installments:
            pdf.drawString(self.MARGIN, y, "Cuotas:")
            y -= 9
            for installment in installments:
                value = self._joined(
                    installment.get("due_date"),
                    self._number(installment.get("amount")),
                    separator=" - ",
                )
                pdf.drawString(self.MARGIN + 5 * mm, y, self._safe(value))
                y -= 9
        return y - 5

    def _draw_items(self, pdf, items, y):
        columns = (
            ("Cod", 15 * mm),
            ("Descripcion", 52 * mm),
            ("UM", 13 * mm),
            ("Cant.", 16 * mm),
            ("P. unit.", 23 * mm),
            ("Desc.", 19 * mm),
            ("Exentas", 20 * mm),
            ("5%", 20 * mm),
            ("10%", 20 * mm),
        )
        x = self.MARGIN
        pdf.setFont("Helvetica-Bold", 6)
        for label, column_width in columns:
            pdf.drawString(x, y, label)
            x += column_width
        y -= 9
        pdf.setFont("Helvetica", 6)
        for item in items:
            description_lines = self._wrap_text(
                item.get("description"),
                50 * mm,
                "Helvetica",
                6,
            )
            rate = self._decimal(item.get("tax_rate"))
            affectation = item.get("tax_affectation")
            total = item.get("total")
            values = (
                item.get("code"),
                description_lines[0],
                item.get("unit_measure_description"),
                self._number(item.get("quantity")),
                self._number(item.get("price_unit")),
                self._number(item.get("discount")),
                self._number(total) if affectation == "3" else "",
                self._number(total) if affectation != "3" and rate == Decimal("5") else "",
                self._number(total) if affectation != "3" and rate == Decimal("10") else "",
            )
            x = self.MARGIN
            for value, (_label, column_width) in zip(values, columns):
                pdf.drawString(x, y, self._safe(value))
                x += column_width
            for continuation in description_lines[1:]:
                y -= 9
                pdf.drawString(self.MARGIN + columns[0][1], y, continuation)
            y -= 9
        return y - 4

    def _paginate_items(self, items):
        pages = []
        current = []
        used_rows = 0
        for item in items:
            rows = max(
                1,
                len(
                    self._wrap_text(
                        item.get("description"),
                        50 * mm,
                        "Helvetica",
                        6,
                    )
                ),
            )
            if current and used_rows + rows > self.ITEMS_PER_PAGE:
                pages.append(current)
                current = []
                used_rows = 0
            current.append(item)
            used_rows += rows
        pages.append(current)
        return pages

    def _draw_totals(self, pdf, payload, y):
        totals = payload["totals"]
        pdf.setFont("Helvetica-Bold", 8)
        rows = (
            ("Subtotal exentas", totals.get("subtotal_exempt")),
            ("Subtotal 5%", totals.get("subtotal_5")),
            ("Subtotal 10%", totals.get("subtotal_10")),
            ("Total de la operacion", totals.get("total_operation")),
            ("Total a pagar", totals.get("total_general")),
            ("Total en Guaranies", totals.get("total_general")),
            ("Liquidacion IVA 5%", totals.get("total_vat_5")),
            ("Liquidacion IVA 10%", totals.get("total_vat_10")),
            ("Total IVA", totals.get("total_vat")),
        )
        for label, value in rows:
            pdf.drawString(self.MARGIN, y, f"{label}: {self._number(value)}")
            y -= 10

    def _draw_qr(self, pdf, cdc, qr_payload):
        width, _height = self.PAGE_SIZE
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
            width - self.MARGIN - self.QR_SIZE,
            self.MARGIN + 10 * mm,
        )
        pdf.setFont("Helvetica", 6)
        parsed = urlsplit(qr_payload)
        consultation_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        pdf.drawString(
            self.MARGIN,
            self.MARGIN + 27,
            "Consulte la validez mediante el codigo QR.",
        )
        pdf.drawString(
            self.MARGIN,
            self.MARGIN + 18,
            f"Consulta SIFEN: {consultation_url}",
        )
        pdf.drawString(self.MARGIN, self.MARGIN + 9, f"CDC: {self._group_cdc(cdc)}")

    def _draw_preview_placeholder(self, pdf):
        width, _height = self.PAGE_SIZE
        x = width - self.MARGIN - self.QR_SIZE
        y = self.MARGIN + 10 * mm
        pdf.setLineWidth(1)
        pdf.rect(x, y, self.QR_SIZE, self.QR_SIZE)
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawCentredString(
            x + self.QR_SIZE / 2,
            y + self.QR_SIZE / 2 + 4,
            "QR NO DISPONIBLE",
        )
        pdf.setFont("Helvetica", 6)
        pdf.drawCentredString(x + self.QR_SIZE / 2, y + self.QR_SIZE / 2 - 6, "Vista previa no fiscal")

    def _draw_preview_mark(self, pdf):
        width, height = self.PAGE_SIZE
        pdf.saveState()
        pdf.setFillGray(0.82)
        pdf.setFont("Helvetica-Bold", 34)
        pdf.translate(width / 2, height / 2)
        pdf.rotate(35)
        pdf.drawCentredString(0, 0, "PREVIEW - SIN VALIDEZ FISCAL")
        pdf.restoreState()

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
