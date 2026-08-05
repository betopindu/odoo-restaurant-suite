from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from xml.etree import ElementTree as ET

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_payload_builder import PyPayloadBuilder


class PyUnsignedXmlBuilder:
    """Build an unsigned SIFEN-oriented Paraguay XML draft from normalized payload."""

    SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
    XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
    SCHEMA_LOCATION = "http://ekuatia.set.gov.py/sifen/xsd siRecepDE_v150.xsd"
    EMISSION_TYPE_DESCRIPTIONS = {
        "1": "Normal",
        "2": "Contingencia",
    }
    DOCUMENT_TYPE_DESCRIPTIONS = {
        "01": "Factura electrónica",
        "04": "Autofactura electrónica",
        "05": "Nota de crédito electrónica",
        "06": "Nota de débito electrónica",
        "07": "Nota de remisión electrónica",
    }
    VAT_AFFECTATION_DESCRIPTIONS = {
        "1": "Gravado IVA",
        "3": "Exento",
        "4": "Gravado parcial (Grav- Exento)",
    }
    RECEIVER_OPERATION_TYPES = {"1", "2", "3", "4"}
    RECEIVER_NATURES = {"1", "2"}

    def __init__(self, env):
        self.env = env

    def build(self, document):
        document.ensure_one()
        payload = PyPayloadBuilder(self.env).build(document)
        document_cdc = payload.get("document", {}).get("py_cdc")
        if payload.get("cdc") != document.py_cdc or document_cdc != document.py_cdc:
            raise ValidationError("Payload CDC must match the fiscal document CDC.")
        return self.build_from_payload(payload)

    def build_from_payload(self, payload):
        self._validate_payload(payload)
        self._validate_xml_readiness(payload)
        ET.register_namespace("", self.SIFEN_NS)
        ET.register_namespace("xsi", self.XSI_NS)
        root = ET.Element(
            self._tag("rDE"),
            {self._xsi_tag("schemaLocation"): self.SCHEMA_LOCATION},
        )
        self._text(root, "dVerFor", payload["version"])

        de = ET.SubElement(root, self._tag("DE"), {"Id": payload["cdc"]})
        self._build_de_preamble(de, payload)
        self._build_electronic_document_operation(de, payload)
        self._build_timbrado(de, payload)
        self._build_general_operation(de, payload)
        self._build_document_type(de, payload)
        self._build_totals(de, payload)

        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _build_de_preamble(self, parent, payload):
        document = payload["document"]
        self._text(parent, "dDVId", document["py_cdc_dv"])
        self._text(parent, "dSisFact", "1")

    def _build_electronic_document_operation(self, parent, payload):
        document = payload["document"]
        emission_type = self._normalize_int_code(document["py_emission_type"])
        group = self._sub(parent, "gOpeDE")
        self._text(group, "iTipEmi", emission_type)
        self._text(group, "dDesTipEmi", self.EMISSION_TYPE_DESCRIPTIONS[emission_type])
        self._text(group, "dCodSeg", document["py_cod_seg"])

    def _build_timbrado(self, parent, payload):
        document = payload["document"]
        issuer = payload["issuer"]
        document_type_code = document["py_i_tide"]
        group = self._sub(parent, "gTimb")
        self._text(group, "iTiDE", self._normalize_int_code(document_type_code))
        self._text(group, "dDesTiDE", self.DOCUMENT_TYPE_DESCRIPTIONS[document_type_code])
        self._text(
            group,
            "dNumTim",
            str(issuer["timbrado_number"]).zfill(8),
        )
        self._text(group, "dEst", issuer["establishment_code"])
        self._text(group, "dPunExp", issuer["point_of_issue_code"])
        self._text(group, "dNumDoc", document["py_document_number"])
        self._text(group, "dFeIniT", self._format_date(issuer.get("timbrado_valid_from")))

    def _build_general_operation(self, parent, payload):
        document = payload["document"]
        group = self._sub(parent, "gDatGralOpe")
        self._text(group, "dFeEmiDE", self._format_datetime(document["issue_datetime"]))
        self._build_commercial_operation(group, payload)
        self._build_issuer(group, payload)
        self._build_receiver(group, payload)

    def _build_commercial_operation(self, parent, payload):
        operation = payload["operation"]
        group = self._sub(parent, "gOpeCom")
        self._text(group, "iTipTra", self._normalize_int_code(operation["transaction_type_code"]))
        self._text(group, "dDesTipTra", operation.get("transaction_type_description"))
        self._text(group, "iTImp", self._normalize_int_code(operation["tax_type_code"]))
        self._text(group, "dDesTImp", operation.get("tax_type_description"))
        self._text(group, "cMoneOpe", operation["currency"])
        self._text(group, "dDesMoneOpe", operation.get("currency_description"))
        self._text(group, "dTiCam", self._format_decimal(operation.get("exchange_rate")))

    def _build_issuer(self, parent, payload):
        issuer = payload["issuer"]
        group = self._sub(parent, "gEmis")
        self._text(group, "dRucEm", issuer["ruc"])
        self._text(group, "dDVEmi", issuer["ruc_dv"])
        self._text(group, "iTipCont", self._normalize_int_code(issuer["taxpayer_type"]))
        self._text(group, "dNomEmi", issuer["name"])
        self._text(group, "dDirEmi", issuer.get("address"))
        self._text(group, "dNumCas", issuer.get("house_number"))
        self._text(group, "cDepEmi", issuer.get("department_code"))
        self._text(group, "dDesDepEmi", issuer.get("department_name"))
        self._text(group, "cDisEmi", issuer.get("district_code"))
        self._text(group, "dDesDisEmi", issuer.get("district_name"))
        self._text(group, "cCiuEmi", issuer.get("city_code"))
        self._text(group, "dDesCiuEmi", issuer.get("city_name"))
        self._text(group, "dTelEmi", issuer.get("phone"))
        self._text(group, "dEmailE", issuer.get("email"))
        self._text(group, "dDenSuc", issuer.get("branch_name"))
        for activity in issuer.get("economic_activities") or []:
            activity_group = self._sub(group, "gActEco")
            self._text(activity_group, "cActEco", activity.get("code"))
            self._text(activity_group, "dDesActEco", activity.get("description"))

    def _build_receiver(self, parent, payload):
        receiver = payload["receiver"]
        nature_code = self._normalize_int_code(receiver["nature_code"])
        group = self._sub(parent, "gDatRec")
        self._text(group, "iNatRec", nature_code)
        self._text(group, "iTiOpe", self._normalize_int_code(receiver["type_code"]))
        self._text(group, "cPaisRec", receiver.get("country_code"))
        self._text(group, "dDesPaisRe", receiver.get("country_description"))
        if nature_code == "1":
            self._text(group, "iTiContRec", self._normalize_int_code(receiver.get("taxpayer_type")))
            self._text(group, "dRucRec", receiver.get("ruc_or_document"))
            self._text(group, "dDVRec", receiver.get("ruc_dv"))
        elif nature_code == "2":
            self._text(group, "iTipIDRec", self._normalize_int_code(receiver.get("id_type")))
            self._text(group, "dDTipIDRec", receiver.get("id_type_description"))
            self._text(group, "dNumIDRec", receiver.get("id_number"))
        self._text(group, "dNomRec", receiver["name"])
        self._text(group, "dDirRec", receiver.get("address"))
        self._text(group, "dNumCasRec", receiver.get("house_number"))
        self._text(group, "cDepRec", receiver.get("department_code"))
        self._text(group, "dDesDepRec", receiver.get("department_name"))
        self._text(group, "cDisRec", receiver.get("district_code"))
        self._text(group, "dDesDisRec", receiver.get("district_name"))
        self._text(group, "cCiuRec", receiver.get("city_code"))
        self._text(group, "dDesCiuRec", receiver.get("city_name"))
        self._text(group, "dTelRec", receiver.get("phone"))
        self._text(group, "dEmailRec", receiver.get("email"))
        self._text(group, "dCodCliente", receiver.get("customer_code"))

    def _build_document_type(self, parent, payload):
        group = self._sub(parent, "gDtipDE")
        if payload["document"]["py_i_tide"] == "01":
            self._build_invoice_fields(group)
        self._build_condition(group, payload)
        for item in payload["items"]:
            self._build_item(group, item)

    def _build_invoice_fields(self, parent):
        group = self._sub(parent, "gCamFE")
        self._text(group, "iIndPres", "1")
        self._text(group, "dDesIndPres", "Operación presencial")

    def _build_condition(self, parent, payload):
        condition = payload["condition"]
        group = self._sub(parent, "gCamCond")
        self._text(group, "iCondOpe", self._normalize_int_code(condition["sale_condition_code"]))
        self._text(group, "dDCondOpe", condition.get("sale_condition_description"))
        payment = self._sub(group, "gPaConEIni")
        self._text(payment, "iTiPago", self._normalize_int_code(condition.get("payment_type_code")))
        self._text(payment, "dDesTiPag", condition.get("payment_type_description"))
        self._text(payment, "dMonTiPag", self._format_money(condition.get("payment_amount")))
        self._text(payment, "cMoneTiPag", condition.get("payment_currency"))
        self._text(payment, "dDMoneTiPag", condition.get("payment_currency_description"))

    def _build_item(self, parent, item):
        group = self._sub(parent, "gCamItem")
        self._text(group, "dCodInt", item.get("code"))
        self._text(group, "dDesProSer", item["description"])
        self._text(group, "cUniMed", item.get("unit_measure_code"))
        self._text(group, "dDesUniMed", item.get("unit_measure_description"))
        self._text(group, "dCantProSer", self._format_decimal(item["quantity"]))

        values = self._sub(group, "gValorItem")
        self._text(values, "dPUniProSer", self._format_money(item["price_unit"]))
        self._text(values, "dTotBruOpeItem", self._format_money(item["total"]))
        remainder = self._sub(values, "gValorRestaItem")
        self._text(remainder, "dDescItem", self._format_money(item.get("discount") or 0))
        self._text(remainder, "dPorcDesIt", self._format_decimal(item.get("discount_percent") or 0))
        self._text(remainder, "dDescGloItem", self._format_money(item.get("global_discount") or 0))
        self._text(remainder, "dAntPreUniIt", self._format_money(item.get("unit_advance") or 0))
        self._text(remainder, "dAntGloPreUniIt", self._format_money(item.get("global_advance") or 0))
        self._text(remainder, "dTotOpeItem", self._format_money(item["total"]))

        tax = self._sub(group, "gCamIVA")
        affectation = item["tax_affectation"]
        self._text(tax, "iAfecIVA", self._normalize_int_code(affectation))
        self._text(tax, "dDesAfecIVA", item.get("tax_affectation_description"))
        self._text(tax, "dPropIVA", self._format_decimal(item.get("tax_proportion")))
        self._text(tax, "dTasaIVA", self._format_rate(item.get("tax_rate")))
        self._text(tax, "dBasGravIVA", self._format_money(item.get("tax_base")))
        self._text(tax, "dLiqIVAItem", self._format_money(item.get("tax_amount")))
        self._text(tax, "dBasExe", self._format_money(item.get("exempt_base") or 0))

    def _build_totals(self, parent, payload):
        totals = payload["totals"]
        subtotal_5 = totals.get("subtotal_5") or 0
        subtotal_10 = totals.get("subtotal_10") or 0
        group = self._sub(parent, "gTotSub")
        self._text(group, "dSubExe", self._format_money(totals.get("subtotal_exempt")))
        self._text(group, "dSub5", self._format_money(subtotal_5))
        self._text(group, "dSub10", self._format_money(subtotal_10))
        self._text(group, "dTotOpe", self._format_money(totals.get("total_operation")))
        self._text(group, "dTotDesc", self._format_money(totals.get("total_discount")))
        self._text(group, "dTotDescGlotem", self._format_money(0))
        self._text(group, "dTotAntItem", self._format_money(0))
        self._text(group, "dTotAnt", self._format_money(0))
        self._text(group, "dPorcDescTotal", self._format_decimal(0))
        self._text(group, "dDescTotal", self._format_money(0))
        self._text(group, "dAnticipo", self._format_money(0))
        self._text(group, "dRedon", self._format_decimal(0, places=4))
        self._text(group, "dTotGralOpe", self._format_money(totals["total_general"]))
        self._text(group, "dIVA5", self._format_money(totals.get("total_vat_5")))
        self._text(group, "dIVA10", self._format_money(totals.get("total_vat_10")))
        self._text(group, "dTotIVA", self._format_money(totals.get("total_vat")))
        self._text(group, "dBaseGrav5", self._format_money(subtotal_5))
        self._text(group, "dBaseGrav10", self._format_money(subtotal_10))
        self._text(group, "dTBasGraIVA", self._format_money(self._decimal(subtotal_5) + self._decimal(subtotal_10)))

    def _validate_payload(self, payload):
        missing = []
        document = payload.get("document") or {}
        issuer = payload.get("issuer") or {}
        receiver = payload.get("receiver") or {}
        operation = payload.get("operation") or {}
        condition = payload.get("condition") or {}
        items = payload.get("items") or []
        totals = payload.get("totals") or {}

        self._require(missing, payload, "version", "payload version")
        self._require(missing, payload, "cdc", "payload CDC")
        self._require(missing, document, "py_i_tide", "document type code")
        self._require(missing, document, "py_document_number", "document number")
        self._require(missing, document, "py_cdc_dv", "CDC check digit")
        self._require(missing, document, "issue_datetime", "issue datetime")
        self._require(missing, document, "py_emission_type", "emission type")
        self._require(missing, document, "py_cod_seg", "security code")
        self._require(missing, issuer, "ruc", "issuer RUC")
        self._require(missing, issuer, "ruc_dv", "issuer RUC DV")
        self._require(missing, issuer, "name", "issuer name")
        self._require(missing, issuer, "taxpayer_type", "issuer taxpayer type")
        self._require(missing, issuer, "establishment_code", "establishment code")
        self._require(missing, issuer, "point_of_issue_code", "point of issue code")
        self._require(missing, issuer, "timbrado_number", "timbrado number")
        self._require(missing, receiver, "nature_code", "receiver nature")
        self._require(missing, receiver, "type_code", "receiver operation type")
        self._require(missing, receiver, "name", "receiver name")
        self._require(missing, operation, "transaction_type_code", "transaction type")
        self._require(missing, operation, "tax_type_code", "tax type")
        self._require(missing, operation, "currency", "currency")
        self._require(missing, condition, "sale_condition_code", "sale condition")
        self._require(missing, totals, "total_general", "total general")

        if payload.get("cdc") != document.get("py_cdc"):
            missing.append("payload CDC must match document CDC")
        if document.get("py_i_tide") and document.get("py_i_tide") not in self.DOCUMENT_TYPE_DESCRIPTIONS:
            missing.append("document type description mapping")
        if (
            document.get("py_emission_type")
            and self._normalize_int_code(document.get("py_emission_type"))
            not in self.EMISSION_TYPE_DESCRIPTIONS
        ):
            missing.append("emission type description mapping")
        if not items:
            missing.append("at least one item")
        for index, item in enumerate(items, start=1):
            prefix = f"item {index}"
            self._require(missing, item, "description", f"{prefix} description")
            self._require(missing, item, "quantity", f"{prefix} quantity")
            self._require(missing, item, "price_unit", f"{prefix} price unit")
            self._require(missing, item, "total", f"{prefix} total")
            self._require(missing, item, "tax_affectation", f"{prefix} tax affectation")
            if (
                item.get("tax_affectation")
                and item.get("tax_affectation") not in self.VAT_AFFECTATION_DESCRIPTIONS
            ):
                missing.append(f"{prefix} VAT affectation description mapping")
            if item.get("tax_affectation") in ("1", "4"):
                self._require(missing, item, "tax_rate", f"{prefix} tax rate")
                self._require(missing, item, "tax_base", f"{prefix} tax base")
                self._require(missing, item, "tax_amount", f"{prefix} tax amount")

        if missing:
            raise ValidationError(
                "Cannot build Paraguay unsigned XML; missing or invalid fields: "
                + "; ".join(missing)
            )

    def _validate_xml_readiness(self, payload):
        missing = []
        document = payload.get("document") or {}
        issuer = payload.get("issuer") or {}
        receiver = payload.get("receiver") or {}
        operation = payload.get("operation") or {}
        condition = payload.get("condition") or {}
        items = payload.get("items") or []

        emission_type = self._normalize_int_code(document.get("py_emission_type"))
        if emission_type and emission_type not in self.EMISSION_TYPE_DESCRIPTIONS:
            missing.append("official emission type description mapping")
        if operation.get("transaction_type_code") and not operation.get("transaction_type_description"):
            missing.append("official transaction type description mapping")
        if operation.get("tax_type_code") and not operation.get("tax_type_description"):
            missing.append("official tax type description mapping")
        if operation.get("currency") and not operation.get("currency_description"):
            missing.append("currency description")
        if condition.get("sale_condition_code") and not condition.get("sale_condition_description"):
            missing.append("official sale condition description mapping")
        if condition.get("payment_type_code") and not condition.get("payment_type_description"):
            missing.append("official payment type description mapping")
        if condition.get("payment_currency") and not condition.get("payment_currency_description"):
            missing.append("payment currency description")
        self._validate_issuer_schema_readiness(issuer, missing)
        self._validate_receiver_schema_readiness(receiver, missing)

        for index, item in enumerate(items, start=1):
            prefix = f"item {index}"
            if not self._has_value(item.get("code")):
                missing.append(f"{prefix} internal code")
            affectation = item.get("tax_affectation")
            if affectation and affectation not in self.VAT_AFFECTATION_DESCRIPTIONS:
                missing.append(f"{prefix} official VAT affectation description mapping")
            if affectation and not item.get("tax_affectation_description"):
                missing.append(f"{prefix} VAT affectation description")

        if missing:
            raise ValidationError(
                "Cannot build Paraguay unsigned XML; payload is not schema-ready: "
                + "; ".join(missing)
            )

    def _validate_issuer_schema_readiness(self, issuer, missing):
        required_fields = [
            ("house_number", "issuer establishment house number"),
            ("department_code", "issuer establishment department code"),
            ("department_name", "issuer establishment department name"),
            ("district_code", "issuer establishment district code"),
            ("district_name", "issuer establishment district name"),
            ("city_code", "issuer establishment city code"),
            ("city_name", "issuer establishment city name"),
            ("branch_name", "issuer establishment branch name"),
        ]
        for key, label in required_fields:
            self._require(missing, issuer, key, label)

        activities = issuer.get("economic_activities") or []
        if not activities:
            missing.append("issuer economic activities")
            return
        for index, activity in enumerate(activities, start=1):
            self._require(missing, activity, "code", f"issuer economic activity {index} code")
            self._require(
                missing,
                activity,
                "description",
                f"issuer economic activity {index} description",
            )

    def _validate_receiver_schema_readiness(self, receiver, missing):
        nature_code = self._normalize_int_code(receiver.get("nature_code"))
        type_code = self._normalize_int_code(receiver.get("type_code"))
        if nature_code and nature_code not in self.RECEIVER_NATURES:
            missing.append("receiver nature mapping")
        if type_code and type_code not in self.RECEIVER_OPERATION_TYPES:
            missing.append("receiver operation type mapping")

        required_fields = [
            ("country_description", "receiver country description"),
            ("house_number", "receiver house number"),
            ("department_code", "receiver department code"),
            ("department_name", "receiver department name"),
            ("district_code", "receiver district code"),
            ("district_name", "receiver district name"),
            ("city_code", "receiver city code"),
            ("city_name", "receiver city name"),
        ]
        for key, label in required_fields:
            self._require(missing, receiver, key, label)

        if nature_code == "1":
            self._require(missing, receiver, "taxpayer_type", "receiver taxpayer type")
            self._require(missing, receiver, "ruc_or_document", "receiver RUC")
            self._require(missing, receiver, "ruc_dv", "receiver RUC DV")
        elif nature_code == "2":
            self._require(missing, receiver, "id_type", "receiver ID type")
            self._require(missing, receiver, "id_type_description", "receiver ID type description")
            self._require(missing, receiver, "id_number", "receiver ID number")

    def _require(self, missing, section, key, label):
        if not self._has_value(section.get(key)):
            missing.append(label)

    def _has_value(self, value):
        return value is not None and value is not False and value != ""

    def _tag(self, tag):
        return f"{{{self.SIFEN_NS}}}{tag}"

    def _xsi_tag(self, tag):
        return f"{{{self.XSI_NS}}}{tag}"

    def _sub(self, parent, tag):
        return ET.SubElement(parent, self._tag(tag))

    def _text(self, parent, tag, value):
        if not self._has_value(value):
            return None
        child = self._sub(parent, tag)
        child.text = str(value)
        return child

    def _decimal(self, value):
        if not self._has_value(value):
            return Decimal("0")
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise ValidationError(f"Invalid numeric value for XML: {value}") from error

    def _format_decimal(self, value, places=8):
        if not self._has_value(value):
            return None
        quant = Decimal("1").scaleb(-places)
        return format(self._decimal(value).quantize(quant, rounding=ROUND_HALF_UP), "f")

    def _format_money(self, value):
        return self._format_decimal(value, places=8)

    def _format_rate(self, value):
        if not self._has_value(value):
            return None
        decimal_value = self._decimal(value)
        if decimal_value == decimal_value.to_integral_value():
            return str(decimal_value.quantize(Decimal("1")))
        return self._format_decimal(decimal_value, places=4)

    def _format_date(self, value):
        if not self._has_value(value):
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        text = str(value)
        if "T" in text:
            return text.split("T", 1)[0]
        if " " in text:
            return text.split(" ", 1)[0]
        return text

    def _format_datetime(self, value):
        if not self._has_value(value):
            return None
        if isinstance(value, datetime):
            return value.replace(microsecond=0).isoformat()
        text = str(value)
        if "T" in text:
            return text.split(".", 1)[0]
        if " " in text:
            return text.split(".", 1)[0].replace(" ", "T", 1)
        return text

    def _normalize_int_code(self, value):
        if not self._has_value(value):
            return None
        text = str(value)
        if text.isdigit():
            return str(int(text))
        return text
