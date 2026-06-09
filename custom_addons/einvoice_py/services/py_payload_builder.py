from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.cdc_service import PyCdcService
from odoo.addons.einvoice_py.services.numbering_service import PyNumberingService


class PyPayloadBuilder:
    VERSION = "150"
    TRANSACTION_TYPES = {
        "1": "Venta de mercadería",
        "2": "Prestación de servicios",
    }
    TAX_TYPES = {
        "1": "IVA",
        "4": "Ninguno",
    }
    RECEIVER_NATURES = {
        "1": "Taxpayer",
        "2": "Non-taxpayer",
    }
    RECEIVER_OPERATION_TYPES = {
        "1": "B2B",
        "2": "B2C",
        "3": "Foreign",
    }
    SALE_CONDITIONS = {
        "1": "Contado",
        "2": "Crédito",
    }
    PAYMENT_TYPES = {
        "1": "Efectivo",
        "3": "Tarjeta de crédito",
        "5": "Transferencia bancaria",
        "17": "Pago Móvil",
    }
    VAT_AFFECTATIONS = {
        "1": "Gravado IVA",
        "3": "Exento",
        "4": "Gravado parcial (Grav- Exento)",
    }
    CURRENCIES = {
        "PYG": "Guarani",
    }

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
            "condition": self._condition_section(document, warnings),
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
        transaction_type_code = document.py_transaction_type_code or "2"
        tax_type_code = document.py_tax_type_code or "1"
        currency = document.py_currency or (document.currency_id.name if document.currency_id else "PYG")
        if not document.py_transaction_type_code:
            warnings.append("Defaulted transaction type for Paraguay payload.")
        if not document.py_tax_type_code:
            warnings.append("Defaulted tax type for Paraguay payload.")
        if not document.py_currency:
            warnings.append("Defaulted currency for Paraguay payload.")
        if currency != "PYG" and not document.py_exchange_rate:
            warnings.append("Currency is not PYG; exchange rate is not modeled yet.")
        return {
            "transaction_type_code": transaction_type_code,
            "transaction_type_description": self.TRANSACTION_TYPES.get(transaction_type_code),
            "tax_type_code": tax_type_code,
            "tax_type_description": self.TAX_TYPES.get(tax_type_code),
            "currency": currency or "PYG",
            "currency_description": self._currency_description(currency),
            "exchange_rate": document.py_exchange_rate or None,
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
        address = document.py_receiver_address or (partner.contact_address if partner else None)
        if not tax_dv:
            warnings.append("Receiver RUC/document DV is missing.")
        if not email:
            warnings.append("Receiver email is missing.")
        if not address:
            warnings.append("Receiver address is missing.")
        if not document.py_receiver_nature:
            warnings.append("Receiver nature is missing.")
        if not document.py_receiver_operation_type:
            warnings.append("Receiver operation type is missing.")
        return {
            "name": document.customer_name or partner.name,
            "ruc_or_document": tax_id,
            "ruc_dv": tax_dv,
            "email": email,
            "address": address,
            "phone": document.py_receiver_phone or partner.phone,
            "country_code": (
                document.py_receiver_country_code
                or (partner.country_id.code if partner and partner.country_id else "PRY")
            ),
            "nature_code": document.py_receiver_nature,
            "nature_description": self.RECEIVER_NATURES.get(document.py_receiver_nature),
            "type_code": document.py_receiver_operation_type,
            "type_description": self.RECEIVER_OPERATION_TYPES.get(
                document.py_receiver_operation_type
            ),
        }

    def _condition_section(self, document, warnings):
        sale_condition_code = document.py_sale_condition_code or "1"
        payment_type_code = document.py_payment_type_code or "1"
        payment_currency = document.py_payment_currency or "PYG"
        if not document.py_sale_condition_code:
            warnings.append("Defaulted sale condition for Paraguay payload.")
        if not document.py_payment_type_code:
            warnings.append("Defaulted payment type for Paraguay payload.")
        if not document.py_payment_currency:
            warnings.append("Defaulted payment currency for Paraguay payload.")
        return {
            "sale_condition_code": sale_condition_code,
            "sale_condition_description": self.SALE_CONDITIONS.get(sale_condition_code),
            "payment_type_code": payment_type_code,
            "payment_type_description": self.PAYMENT_TYPES.get(payment_type_code),
            "payment_amount": document.py_payment_amount or document.amount_total,
            "payment_currency": payment_currency,
            "payment_currency_description": self._currency_description(payment_currency),
        }

    def _items_section(self, document, warnings):
        items = []
        for line in document.line_ids:
            tax_rate = line.py_tax_rate if line.py_tax_rate is not False else line.tax_rate
            tax_base = line.py_tax_base or line.tax_base_amount
            tax_amount = line.py_tax_amount or line.tax_amount
            if not line.py_tax_affectation:
                warnings.append(
                    f"Line {line.sequence or line.id}: tax affectation is missing."
                )
            if line.py_tax_affectation != "3" and not tax_rate and not tax_amount:
                warnings.append(
                    f"Line {line.sequence or line.id}: unknown item tax details."
                )
            items.append({
                "code": line.py_internal_code or line.product_code or line.fiscal_product_code,
                "description": line.description or line.product_name,
                "quantity": line.quantity,
                "unit_measure_code": line.py_unit_measure_code or "77",
                "unit_measure_description": line.py_unit_measure_description or "UNI",
                "price_unit": line.price_unit,
                "discount": line.py_discount_amount or line.discount,
                "discount_percent": 0,
                "global_discount": 0,
                "unit_advance": 0,
                "global_advance": 0,
                "total": line.total,
                "tax_affectation": line.py_tax_affectation,
                "tax_affectation_description": self.VAT_AFFECTATIONS.get(line.py_tax_affectation),
                "tax_rate": tax_rate,
                "tax_proportion": line.py_tax_proportion,
                "tax_base": tax_base,
                "tax_amount": tax_amount,
                "exempt_base": line.py_exempt_base,
            })
        return items

    def _totals_section(self, document, warnings):
        subtotal_exempt = subtotal_5 = subtotal_10 = 0.0
        total_vat_5 = total_vat_10 = 0.0
        for line in document.line_ids:
            rate = line.py_tax_rate
            tax_amount = line.py_tax_amount or 0.0
            if line.py_tax_affectation == "3":
                subtotal_exempt += line.py_exempt_base or line.total
            elif rate == 5:
                subtotal_5 += line.py_tax_base or line.total
                total_vat_5 += tax_amount
            elif rate == 10:
                subtotal_10 += line.py_tax_base or line.total
                total_vat_10 += tax_amount
            elif line.py_tax_affectation == "4":
                subtotal_exempt += line.py_exempt_base or 0.0
                if rate == 5:
                    subtotal_5 += line.py_tax_base or 0.0
                    total_vat_5 += tax_amount
                elif rate == 10:
                    subtotal_10 += line.py_tax_base or 0.0
                    total_vat_10 += tax_amount
                else:
                    warnings.append(
                        f"Line {line.sequence or line.id}: partial tax rate is missing."
                    )
            else:
                warnings.append(
                    f"Line {line.sequence or line.id}: tax bucket could not be determined."
                )
        return {
            "subtotal_exempt": subtotal_exempt,
            "subtotal_5": subtotal_5,
            "subtotal_10": subtotal_10,
            "total_operation": document.amount_total,
            "total_discount": document.amount_discount
            or sum(line.py_discount_amount or 0.0 for line in document.line_ids),
            "total_vat_5": total_vat_5,
            "total_vat_10": total_vat_10,
            "total_vat": total_vat_5 + total_vat_10,
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

    def _currency_description(self, code):
        if not code:
            return None
        return self.CURRENCIES.get(code, code)
