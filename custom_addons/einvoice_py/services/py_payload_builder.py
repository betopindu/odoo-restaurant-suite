import json
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
        "10": "Compra de productos",
        "11": "Compra de servicios",
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
        "2": "Cheque",
        "3": "Tarjeta de crédito",
        "4": "Tarjeta de débito",
        "5": "Transferencia",
        "6": "Giro",
        "7": "Billetera electrónica",
        "8": "Tarjeta empresarial",
        "9": "Vale",
        "10": "Retención",
        "11": "Pago por anticipo",
        "12": "Valor fiscal",
        "13": "Valor comercial",
        "14": "Compensación",
        "15": "Permuta",
        "16": "Pago bancario",
        "17": "Pago Móvil",
        "18": "Donación",
        "19": "Promoción",
        "20": "Consumo Interno",
        "21": "Pago Electrónico",
        "99": "Otro",
    }
    CARD_DENOMINATIONS = {
        "1": "Visa", "2": "Mastercard", "3": "American Express",
        "4": "Maestro", "5": "Panal", "6": "Cabal", "99": "Otro",
    }
    CARD_PROCESSING_TYPES = {"1", "2", "9"}
    VAT_AFFECTATIONS = {
        "1": "Gravado IVA",
        "3": "Exento",
        "4": "Gravado parcial (Grav- Exento)",
    }
    CURRENCIES = {
        "PYG": "Guarani",
    }
    CREDIT_DEBIT_REASONS = {
        "1": "Devolución y Ajuste de precios",
        "2": "Devolución",
        "3": "Descuento",
        "4": "Bonificación",
        "5": "Crédito incobrable",
        "6": "Recupero de costo",
        "7": "Recupero de gasto",
        "8": "Ajuste de precio",
    }
    SELLER_NATURES = {"1": "No contribuyente", "2": "Extranjero"}
    SELLER_ID_TYPES = {
        "1": "Cédula paraguaya", "2": "Pasaporte",
        "3": "Cédula extranjera", "4": "Carnet de residencia",
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
            "environment": document.environment,
            "cdc": document.py_cdc,
            "document": self._document_section(document),
            "operation": self._operation_section(document, warnings),
            "issuer": self._issuer_section(document, warnings),
            "receiver": self._receiver_section(document, warnings),
            "items": items,
            "totals": self._totals_section(document, warnings, items),
            "paraguay": self._paraguay_section(document),
            "warnings": warnings,
        }
        if document.document_type in ("invoice", "self_invoice"):
            payload["condition"] = self._condition_section(document, warnings)
        if document.document_type in ("credit_note", "debit_note"):
            payload["credit_debit_note"] = self._credit_debit_note_section(document)
            payload["associated_document"] = self._associated_document_section(document)
        if document.document_type == "self_invoice":
            payload["self_invoice"] = self._self_invoice_section(document)
            payload["associated_document"] = self._associated_document_section(document)
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
        if document.document_type in ("credit_note", "debit_note"):
            if not document.py_credit_debit_reason_code:
                missing.append("Credit/debit note reason is required.")
            original = document.original_document_id
            if (
                not original
                or original.document_type != "invoice"
                or not original.py_cdc
                or len(original.py_cdc) != 44
            ):
                missing.append("An electronic original invoice with a valid CDC is required.")
        if document.document_type == "self_invoice":
            required = (
                (document.py_seller_nature, "Self-invoice seller nature is required."),
                (document.py_seller_id_type, "Self-invoice seller ID type is required."),
                (document.py_seller_id_number, "Self-invoice seller ID is required."),
                (document.py_seller_name, "Self-invoice seller name is required."),
                (document.py_seller_address, "Self-invoice seller address is required."),
                (document.py_seller_house_number, "Self-invoice seller house number is required."),
                (document.py_seller_department_code, "Self-invoice seller department is required."),
                (document.py_seller_department_name, "Self-invoice seller department description is required."),
                (document.py_seller_city_code, "Self-invoice seller city is required."),
                (document.py_seller_city_name, "Self-invoice seller city description is required."),
                (document.py_transaction_address, "Self-invoice transaction address is required."),
                (document.py_transaction_department_code, "Self-invoice transaction department is required."),
                (document.py_transaction_department_name, "Self-invoice transaction department description is required."),
                (document.py_transaction_city_code, "Self-invoice transaction city is required."),
                (document.py_transaction_city_name, "Self-invoice transaction city description is required."),
            )
            missing.extend(message for value, message in required if not value)
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
        transaction_type_required = document.document_type in ("invoice", "self_invoice")
        transaction_type_code = (
            document.py_transaction_type_code or "2"
            if transaction_type_required
            else None
        )
        tax_type_code = document.py_tax_type_code or "1"
        currency = document.py_currency or (document.currency_id.name if document.currency_id else "PYG")
        if transaction_type_required and not document.py_transaction_type_code:
            warnings.append("Defaulted transaction type for Paraguay payload.")
        if not document.py_tax_type_code:
            warnings.append("Defaulted tax type for Paraguay payload.")
        if not document.py_currency:
            warnings.append("Defaulted currency for Paraguay payload.")
        if currency != "PYG" and not document.py_exchange_rate:
            warnings.append("Currency is not PYG; exchange rate is not modeled yet.")
        return {
            "transaction_type_code": transaction_type_code,
            "transaction_type_description": (
                self.TRANSACTION_TYPES.get(transaction_type_code)
                if transaction_type_code
                else None
            ),
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
            "timbrado_valid_to": (
                timbrado.valid_to.isoformat()
                if timbrado.valid_to
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
        is_innominado = (
            document.py_receiver_nature == "2"
            and document.py_receiver_id_type == "5"
        )
        address = document.py_receiver_address or (
            partner.contact_address
            if partner and not is_innominado
            else None
        )
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
        condition = {
            "sale_condition_code": sale_condition_code,
            "sale_condition_description": self.SALE_CONDITIONS.get(sale_condition_code),
            "payment_type_code": payment_type_code,
            "payment_type_description": self.PAYMENT_TYPES.get(payment_type_code),
            "payment_amount": document.py_payment_amount or document.amount_total,
            "payment_currency": payment_currency,
            "payment_currency_description": self._currency_description(payment_currency),
        }
        if sale_condition_code == "1":
            condition["payments"] = self._cash_payments(document, condition)
        if sale_condition_code == "2":
            try:
                installments = json.loads(document.py_installments_json or "[]")
            except (TypeError, ValueError) as error:
                raise ValidationError("Credit installment snapshot is invalid.") from error
            if not isinstance(installments, list) or not installments:
                if document.source_model == "account.move":
                    raise ValidationError("Credit installment snapshot is required.")
                warnings.append(
                    "Legacy credit document has no immutable accounting installment snapshot."
                )
                return condition
            if document.py_installment_count != len(installments):
                raise ValidationError("Credit installment count does not match its snapshot.")
            try:
                installment_total = sum(
                    (Decimal(str(item["amount"])) for item in installments),
                    Decimal("0"),
                )
            except (KeyError, TypeError, InvalidOperation) as error:
                raise ValidationError("Credit installment amounts are invalid.") from error
            if document.currency_id.compare_amounts(
                float(installment_total), document.amount_total
            ) != 0:
                raise ValidationError(
                    "Credit installment amounts do not reconcile with the fiscal total."
                )
            if any(
                not isinstance(item, dict)
                or not item.get("due_date")
                or item.get("currency") != "PYG"
                or Decimal(str(item.get("amount") or 0)) <= 0
                for item in installments
            ):
                raise ValidationError("Credit installment snapshot is incomplete or invalid.")
            condition.update({
                "credit_condition_code": document.py_credit_condition_code,
                "credit_condition_description": (
                    "Cuota" if document.py_credit_condition_code == "2" else "Plazo"
                ),
                "credit_term": document.py_credit_term or None,
                "installment_count": document.py_installment_count,
                "initial_payment": document.py_payment_amount or 0,
                "installments": [
                    {
                        "sequence": item.get("sequence"),
                        "currency": item.get("currency"),
                        "currency_description": self._currency_description(item.get("currency")),
                        "amount": item.get("amount"),
                        "due_date": item.get("due_date"),
                        "source_move_line_id": item.get("source_move_line_id"),
                    }
                    for item in installments
                ],
            })
        return condition

    def _cash_payments(self, document, legacy):
        if not document.py_payments_json:
            return [{
                "sequence": 1,
                "type_code": legacy["payment_type_code"],
                "type_description": legacy["payment_type_description"],
                "amount": legacy["payment_amount"],
                "currency": legacy["payment_currency"],
                "currency_description": legacy["payment_currency_description"],
            }]
        try:
            snapshot = json.loads(document.py_payments_json)
        except (TypeError, ValueError) as error:
            raise ValidationError("POS payment snapshot is invalid.") from error
        if not isinstance(snapshot, list) or not snapshot:
            raise ValidationError("POS payment snapshot is empty.")
        payments = []
        total = Decimal("0")
        for index, item in enumerate(snapshot, 1):
            if not isinstance(item, dict):
                raise ValidationError("POS payment snapshot is invalid.")
            code = str(item.get("type_code") or "")
            description = self.PAYMENT_TYPES.get(code)
            currency = item.get("currency")
            try:
                amount = Decimal(str(item.get("amount")))
            except (TypeError, InvalidOperation) as error:
                raise ValidationError("POS payment snapshot amount is invalid.") from error
            if not description or currency != "PYG" or amount <= 0:
                raise ValidationError("POS payment snapshot is incomplete or unsupported.")
            payment = {
                "sequence": index,
                "type_code": code,
                "type_description": description,
                "amount": format(amount, "f"),
                "currency": currency,
                "currency_description": self._currency_description(currency),
            }
            card = item.get("card")
            if code in ("3", "4"):
                payment["card"] = self._validated_card_payment(card)
            elif card:
                raise ValidationError("Card detail is only valid for card payments.")
            payments.append(payment)
            total += amount
        if document.py_payment_count != len(payments):
            raise ValidationError("POS payment count does not match its snapshot.")
        if document.currency_id.compare_amounts(float(total), document.amount_total) != 0:
            raise ValidationError("POS payment snapshot does not reconcile with the fiscal total.")
        return payments

    def _validated_card_payment(self, card):
        if not isinstance(card, dict):
            raise ValidationError("Card payment requires its immutable SIFEN detail.")
        denomination = str(card.get("denomination_code") or "")
        processing = str(card.get("processing_code") or "")
        expected_description = self.CARD_DENOMINATIONS.get(denomination)
        if (
            not expected_description
            or card.get("denomination_description") != expected_description
            or processing not in self.CARD_PROCESSING_TYPES
        ):
            raise ValidationError("Card payment SIFEN detail is incomplete or invalid.")
        processor = (
            card.get("processor_name"), card.get("processor_ruc"), card.get("processor_dv")
        )
        if any(processor) and not all(processor):
            raise ValidationError("Card processor identity must be complete when provided.")
        if card.get("processor_ruc") and (
            not str(card["processor_ruc"]).isdigit()
            or not 3 <= len(str(card["processor_ruc"])) <= 8
            or not str(card["processor_dv"]).isdigit()
            or len(str(card["processor_dv"])) != 1
        ):
            raise ValidationError("Card processor RUC and DV are invalid.")
        return {
            "denomination_code": denomination,
            "denomination_description": expected_description,
            "processing_code": processing,
            "processor_name": card.get("processor_name") or None,
            "processor_ruc": card.get("processor_ruc") or None,
            "processor_dv": card.get("processor_dv") or None,
        }

    def _self_invoice_section(self, document):
        return {
            "seller_nature": document.py_seller_nature,
            "seller_nature_description": self.SELLER_NATURES.get(document.py_seller_nature),
            "seller_id_type": document.py_seller_id_type,
            "seller_id_type_description": self.SELLER_ID_TYPES.get(document.py_seller_id_type),
            "seller_id_number": document.py_seller_id_number,
            "seller_name": document.py_seller_name,
            "seller_address": document.py_seller_address,
            "seller_house_number": document.py_seller_house_number,
            "seller_department_code": document.py_seller_department_code,
            "seller_department_name": document.py_seller_department_name,
            "seller_district_code": document.py_seller_district_code,
            "seller_district_name": document.py_seller_district_name,
            "seller_city_code": document.py_seller_city_code,
            "seller_city_name": document.py_seller_city_name,
            "transaction_address": document.py_transaction_address,
            "transaction_department_code": document.py_transaction_department_code,
            "transaction_department_name": document.py_transaction_department_name,
            "transaction_district_code": document.py_transaction_district_code,
            "transaction_district_name": document.py_transaction_district_name,
            "transaction_city_code": document.py_transaction_city_code,
            "transaction_city_name": document.py_transaction_city_name,
        }

    def _credit_debit_note_section(self, document):
        if document.document_type not in ("credit_note", "debit_note"):
            return None
        code = document.py_credit_debit_reason_code
        return {
            "reason_code": code,
            "reason_description": self.CREDIT_DEBIT_REASONS.get(code),
        }

    def _associated_document_section(self, document):
        if document.document_type == "self_invoice":
            return {
                "type_code": "3",
                "type_description": "Constancia Electrónica",
                "constancy_type_code": "1",
                "constancy_type_description": "Constancia de no ser contribuyente",
            }
        original = document.original_document_id
        if document.document_type not in ("credit_note", "debit_note") or not original:
            return None
        return {
            "type_code": "1",
            "type_description": "Electrónico",
            "cdc": original.py_cdc or original.country_identifier,
            "document_id": original.id,
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
            is_self_invoice = document.document_type == "self_invoice"
            if not line.py_tax_affectation and not is_self_invoice:
                warnings.append(
                    f"Line {line.sequence or line.id}: tax affectation is missing."
                )
            if (
                not is_self_invoice
                and line.py_tax_affectation != "3"
                and not tax_rate
                and not tax_amount
            ):
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
        if document.document_type == "self_invoice":
            total_operation = sum(
                (self._decimal(item["total"]) for item in items), Decimal("0")
            )
            total_discount = sum(
                (
                    self._decimal(item.get("discount") or 0)
                    * self._decimal(item["quantity"])
                    for item in items
                ),
                Decimal("0"),
            )
            return {
                "total_operation": self._number(total_operation),
                "total_discount": self._number(total_discount),
                # dTotIVA remains part of the mandatory QR input even though an
                # AFE must not carry the per-item IVA group.
                "total_vat": 0,
                "total_general": self._number(total_operation),
            }
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
