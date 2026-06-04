from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.cdc_service import PyCdcService
from odoo.addons.einvoice_py.services.numbering_service import PyNumberingService


class PyPayloadBuilder:
    VERSION = "150"

    def __init__(self, env):
        self.env = env

    def build(self, document):
        document.ensure_one()
        warnings = []
        self._validate_required(document)

        payload = {
            "version": self.VERSION,
            "cdc": document.py_cdc,
            "document": self._document_section(document),
            "operation": self._operation_section(document, warnings),
            "issuer": self._issuer_section(document, warnings),
            "receiver": self._receiver_section(document, warnings),
            "condition": self._condition_section(warnings),
            "items": self._items_section(document, warnings),
            "totals": self._totals_section(document, warnings),
            "paraguay": self._paraguay_section(document),
            "warnings": warnings,
        }
        return payload

    def _validate_required(self, document):
        missing = []
        if not document.py_cdc:
            missing.append("Paraguay CDC is required.")
        if not document.py_full_number:
            missing.append("Paraguay full number is required.")
        if not document.py_issuer_ruc:
            missing.append("Paraguay issuer RUC is required.")
        if not document.py_issuer_ruc_dv:
            missing.append("Paraguay issuer RUC DV is required.")
        if not document.py_issuer_taxpayer_type:
            missing.append("Paraguay issuer taxpayer type is required.")
        if not document.py_establishment_id:
            missing.append("Paraguay establishment is required.")
        if not document.py_point_of_issue_id:
            missing.append("Paraguay point of issue is required.")
        if not document.py_timbrado_id:
            missing.append("Paraguay timbrado is required.")
        if not document.line_ids:
            missing.append("At least one fiscal document line is required.")
        if missing:
            raise ValidationError("; ".join(missing))

    def _document_section(self, document):
        return {
            "document_type": document.document_type,
            "py_i_tide": PyCdcService.DOCUMENT_TYPE_CODES.get(document.document_type),
            "py_full_number": document.py_full_number,
            "py_document_number": document.py_document_number,
            "py_cdc": document.py_cdc,
            "py_cdc_base": document.py_cdc_base,
            "py_cdc_dv": document.py_cdc_dv,
            "issue_datetime": (
                document.issue_datetime.isoformat()
                if document.issue_datetime
                else None
            ),
            "py_emission_type": document.py_emission_type,
            "py_cod_seg": document.py_cod_seg,
        }

    def _operation_section(self, document, warnings):
        warnings.extend([
            "Defaulted transaction type for Paraguay payload.",
            "Defaulted tax type for Paraguay payload.",
        ])
        currency = document.currency_id.name if document.currency_id else "PYG"
        if currency != "PYG":
            warnings.append("Currency is not PYG; exchange rate is not modeled yet.")
        return {
            "transaction_type_code": "2",
            "transaction_type_description": "Prestacion de servicios",
            "tax_type_code": "1",
            "tax_type_description": "IVA",
            "currency": currency or "PYG",
            "exchange_rate": None,
        }

    def _issuer_section(self, document, warnings):
        establishment = document.py_establishment_id
        timbrado = document.py_timbrado_id
        issuer = document.py_issuer_id
        company = document.company_id
        return {
            "ruc": document.py_issuer_ruc,
            "ruc_dv": document.py_issuer_ruc_dv,
            "full_ruc": f"{document.py_issuer_ruc}-{document.py_issuer_ruc_dv}",
            "taxpayer_type": document.py_issuer_taxpayer_type,
            "name": issuer.name or company.name,
            "address": establishment.address or company.street,
            "phone": establishment.phone or company.phone,
            "email": establishment.email or company.email,
            "establishment_code": establishment.code,
            "point_of_issue_code": document.py_point_of_issue_id.code,
            "timbrado_number": timbrado.number,
            "timbrado_valid_from": (
                timbrado.valid_from.isoformat()
                if timbrado.valid_from
                else None
            ),
        }

    def _receiver_section(self, document, warnings):
        partner = document.partner_id
        tax_id, tax_dv = self._split_tax_identifier(document.customer_tax_id)
        email = document.customer_email or partner.email
        address = partner.contact_address if partner else None
        if not tax_dv:
            warnings.append("Receiver RUC/document DV is missing.")
        if not email:
            warnings.append("Receiver email is missing.")
        if not address:
            warnings.append("Receiver address is missing.")
        warnings.append("Defaulted receiver nature/type placeholders.")
        return {
            "name": document.customer_name or partner.name,
            "ruc_or_document": tax_id,
            "ruc_dv": tax_dv,
            "email": email,
            "address": address,
            "country_code": partner.country_id.code if partner and partner.country_id else "PRY",
            "nature_code": None,
            "nature_description": None,
            "type_code": None,
            "type_description": None,
        }

    def _condition_section(self, warnings):
        warnings.append("Defaulted sale condition and payment type for Paraguay payload.")
        return {
            "sale_condition_code": "1",
            "sale_condition_description": "Contado",
            "payment_type_code": "1",
            "payment_type_description": "Efectivo",
        }

    def _items_section(self, document, warnings):
        items = []
        for line in document.line_ids:
            if not line.tax_rate and not line.tax_amount:
                warnings.append(
                    f"Line {line.sequence or line.id}: unknown item tax details."
                )
            items.append({
                "code": line.product_code or line.fiscal_product_code,
                "description": line.description or line.product_name,
                "quantity": line.quantity,
                "unit_measure_code": "77",
                "unit_measure_description": "UNI",
                "price_unit": line.price_unit,
                "discount": line.discount,
                "total": line.total,
                "tax_rate": line.tax_rate,
                "tax_base": line.tax_base_amount,
                "tax_amount": line.tax_amount,
            })
        return items

    def _totals_section(self, document, warnings):
        warnings.append("Detailed Paraguay tax buckets are not fully modeled yet.")
        return {
            "subtotal_exempt": 0.0,
            "subtotal_5": 0.0,
            "subtotal_10": document.amount_untaxed,
            "total_operation": document.amount_total,
            "total_discount": document.amount_discount,
            "total_vat_5": 0.0,
            "total_vat_10": document.amount_tax,
            "total_vat": document.amount_tax,
            "total_general": document.amount_total,
        }

    def _paraguay_section(self, document):
        sequence = PyNumberingService(self.env).find_sequence(document)
        return {
            "establishment_id": document.py_establishment_id.id,
            "establishment_code": document.py_establishment_id.code,
            "point_of_issue_id": document.py_point_of_issue_id.id,
            "point_of_issue_code": document.py_point_of_issue_id.code,
            "timbrado_id": document.py_timbrado_id.id,
            "timbrado_number": document.py_timbrado_id.number,
            "csc_id": document.py_csc_id.id if document.py_csc_id else False,
            "id_csc": document.py_csc_id.id_csc if document.py_csc_id else None,
            "sequence_id": sequence.id if sequence else False,
            "sequence_name": sequence.name if sequence else None,
            "sequence_next_number": sequence.next_number if sequence else None,
        }

    def _split_tax_identifier(self, value):
        if not value:
            return None, None
        parts = value.split("-", 1)
        if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 1:
            return parts[0], parts[1]
        return value, None
