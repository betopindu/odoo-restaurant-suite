from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.cdc_service import PyCdcService
from odoo.addons.einvoice_py.services.numbering_service import PyNumberingService
from odoo.addons.einvoice_py.services.py_sifen_datetime_service import (
    PySifenDatetimeService,
)


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
        "3": "B2G",
        "4": "B2F",
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

        items = self._items_section(document, warnings)
        payload = {
            "version": self.VERSION,
            "cdc": document.py_cdc,
            "document": self._document_section(document),
            "operation": self._operation_section(document, warnings),
            "issuer": self._issuer_section(document, warnings),
            "receiver": self._receiver_section(document, warnings),
            "condition": self._condition_section(document, warnings),
            "items": items,
            "totals": self._totals_section(document, warnings, items),
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
                PySifenDatetimeService.format_fiscal_datetime(
                    document.issue_datetime,
                    field_label="Paraguay emission timestamp",
                )
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
        economic_activities = issuer.economic_activity_ids.filtered("active").sorted(
            lambda activity: (activity.sequence, activity.code or "")
        )
        self._add_missing_issuer_schema_warnings(establishment, economic_activities, warnings)
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
            "house_number": establishment.house_number,
            "department_code": establishment.department_code,
            "department_name": establishment.department_name,
            "district_code": establishment.district_code,
            "district_name": establishment.district_name,
            "city_code": establishment.city_code,
            "city_name": establishment.city_name,
            "branch_name": establishment.branch_name,
            "economic_activities": [
                {
                    "code": activity.code,
                    "description": activity.description,
                }
                for activity in economic_activities
            ],
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
        self._add_missing_receiver_schema_warnings(document, warnings)
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
            "country_description": document.py_receiver_country_description,
            "nature_code": document.py_receiver_nature,
            "nature_description": self.RECEIVER_NATURES.get(document.py_receiver_nature),
            "taxpayer_type": document.py_receiver_taxpayer_type,
            "id_type": document.py_receiver_id_type,
            "id_type_description": document.py_receiver_id_type_description,
            "id_number": document.py_receiver_id_number,
            "type_code": document.py_receiver_operation_type,
            "type_description": self.RECEIVER_OPERATION_TYPES.get(
                document.py_receiver_operation_type
            ),
            "house_number": document.py_receiver_house_number,
            "department_code": document.py_receiver_department_code,
            "department_name": document.py_receiver_department_name,
            "district_code": document.py_receiver_district_code,
            "district_name": document.py_receiver_district_name,
            "city_code": document.py_receiver_city_code,
            "city_name": document.py_receiver_city_name,
            "customer_code": document.py_receiver_customer_code,
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
            quantity = self._decimal(line.quantity)
            price_unit = self._decimal(line.price_unit)
            discount = self._decimal(line.py_discount_amount or line.discount or 0)
            gross_total = price_unit * quantity
            total = (price_unit - discount) * quantity
            tax_proportion = self._decimal(line.py_tax_proportion or 0)
            tax_base, tax_amount, exempt_base = self._item_tax_values(
                total=total,
                affectation=line.py_tax_affectation,
                rate=self._decimal(tax_rate or 0),
                proportion=tax_proportion,
            )
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
                "quantity": self._number(quantity),
                "unit_measure_code": line.py_unit_measure_code or "77",
                "unit_measure_description": line.py_unit_measure_description or "UNI",
                "price_unit": self._number(price_unit),
                "discount": self._number(discount),
                "discount_percent": self._number(
                    discount * Decimal("100") / price_unit if price_unit else 0
                ),
                "global_discount": 0,
                "unit_advance": 0,
                "global_advance": 0,
                "gross_total": self._number(gross_total),
                "total": self._number(total),
                "tax_affectation": line.py_tax_affectation,
                "tax_affectation_description": self.VAT_AFFECTATIONS.get(line.py_tax_affectation),
                "tax_rate": tax_rate,
                "tax_proportion": self._number(tax_proportion),
                "tax_base": self._number(tax_base),
                "tax_amount": self._number(tax_amount),
                "exempt_base": self._number(exempt_base),
            })
        return items

    def _totals_section(self, document, warnings, items):
        subtotal_exempt = subtotal_5 = subtotal_10 = Decimal("0")
        base_5 = base_10 = Decimal("0")
        total_vat_5 = total_vat_10 = Decimal("0")
        total_discount = Decimal("0")
        for item in items:
            rate = self._decimal(item.get("tax_rate") or 0)
            item_total = self._decimal(item["total"])
            tax_base = self._decimal(item.get("tax_base") or 0)
            tax_amount = self._decimal(item.get("tax_amount") or 0)
            total_discount += self._decimal(item.get("discount") or 0) * self._decimal(
                item["quantity"]
            )
            if item["tax_affectation"] == "3":
                subtotal_exempt += item_total
            elif item["tax_affectation"] == "4":
                subtotal_exempt += self._decimal(item.get("exempt_base") or 0)
                taxable_subtotal = tax_base + tax_amount
                if rate == 5:
                    subtotal_5 += taxable_subtotal
                    base_5 += tax_base
                    total_vat_5 += tax_amount
                elif rate == 10:
                    subtotal_10 += taxable_subtotal
                    base_10 += tax_base
                    total_vat_10 += tax_amount
                else:
                    warnings.append("Partial tax rate is missing.")
            elif rate == 5:
                subtotal_5 += item_total
                base_5 += tax_base
                total_vat_5 += tax_amount
            elif rate == 10:
                subtotal_10 += item_total
                base_10 += tax_base
                total_vat_10 += tax_amount
            else:
                warnings.append("Tax bucket could not be determined.")
        total_operation = subtotal_exempt + subtotal_5 + subtotal_10
        return {
            "subtotal_exempt": self._number(subtotal_exempt),
            "subtotal_5": self._number(subtotal_5),
            "subtotal_10": self._number(subtotal_10),
            "base_5": self._number(base_5),
            "base_10": self._number(base_10),
            "total_operation": self._number(total_operation),
            "total_discount": self._number(total_discount),
            "total_vat_5": self._number(total_vat_5),
            "total_vat_10": self._number(total_vat_10),
            "total_vat": self._number(total_vat_5 + total_vat_10),
            "total_general": self._number(total_operation),
        }

    def _item_tax_values(self, *, total, affectation, rate, proportion):
        if affectation not in ("1", "4") or not rate:
            exempt = total if affectation == "3" else Decimal("0")
            return Decimal("0"), Decimal("0"), exempt
        taxable_gross = total * proportion / Decimal("100")
        divisor = Decimal("1") + (rate / Decimal("100"))
        base = self._money(taxable_gross / divisor)
        tax = self._money(base * rate / Decimal("100"))
        exempt = self._money(total - taxable_gross) if affectation == "4" else Decimal("0")
        return base, tax, exempt

    def _decimal(self, value):
        try:
            return Decimal(str(value or 0))
        except (InvalidOperation, ValueError):
            raise ValidationError("Invalid Paraguay monetary value.") from None

    def _money(self, value):
        return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

    def _number(self, value):
        return float(self._money(self._decimal(value)))

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

    def _add_missing_issuer_schema_warnings(self, establishment, economic_activities, warnings):
        fields_to_check = [
            ("house_number", "Issuer establishment house number is missing."),
            ("department_code", "Issuer establishment department code is missing."),
            ("department_name", "Issuer establishment department name is missing."),
            ("district_code", "Issuer establishment district code is missing."),
            ("district_name", "Issuer establishment district name is missing."),
            ("city_code", "Issuer establishment city code is missing."),
            ("city_name", "Issuer establishment city name is missing."),
            ("branch_name", "Issuer establishment branch name is missing."),
        ]
        for field_name, message in fields_to_check:
            if not establishment[field_name]:
                warnings.append(message)
        if not economic_activities:
            warnings.append("Issuer economic activities are missing.")

    def _add_missing_receiver_schema_warnings(self, document, warnings):
        if not document.py_receiver_country_description:
            warnings.append("Receiver country description is missing.")
        if document.py_receiver_nature == "1" and not document.py_receiver_taxpayer_type:
            warnings.append("Receiver taxpayer type is missing.")
        if document.py_receiver_nature == "2":
            if not document.py_receiver_id_type:
                warnings.append("Receiver ID type is missing.")
            if not document.py_receiver_id_type_description:
                warnings.append("Receiver ID type description is missing.")
            if not document.py_receiver_id_number:
                warnings.append("Receiver ID number is missing.")
        fields_to_check = [
            ("py_receiver_house_number", "Receiver house number is missing."),
            ("py_receiver_department_code", "Receiver department code is missing."),
            ("py_receiver_department_name", "Receiver department name is missing."),
            ("py_receiver_district_code", "Receiver district code is missing."),
            ("py_receiver_district_name", "Receiver district name is missing."),
            ("py_receiver_city_code", "Receiver city code is missing."),
            ("py_receiver_city_name", "Receiver city name is missing."),
        ]
        for field_name, message in fields_to_check:
            if not document[field_name]:
                warnings.append(message)

    def _currency_description(self, code):
        if not code:
            return None
        return self.CURRENCIES.get(code, code)
