from xml.etree import ElementTree as ET

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_payload_builder import PyPayloadBuilder


class PyUnsignedXmlBuilder:
    """Build an unsigned SIFEN-oriented Paraguay XML draft from normalized payload."""

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
        root = ET.Element("rDE", {"version": str(payload["version"])})
        self._text(root, "dVerFor", payload["version"])

        de = ET.SubElement(root, "DE", {"Id": payload["cdc"]})
        self._build_timbrado(de, payload)
        self._build_general_operation(de, payload)
        self._build_document_type(de, payload)
        self._build_totals(de, payload)

        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _build_timbrado(self, parent, payload):
        document = payload["document"]
        issuer = payload["issuer"]
        group = ET.SubElement(parent, "gTimb")
        self._text(group, "iTiDE", document["py_i_tide"])
        self._text(group, "dNumTim", issuer["timbrado_number"])
        self._text(group, "dEst", issuer["establishment_code"])
        self._text(group, "dPunExp", issuer["point_of_issue_code"])
        self._text(group, "dNumDoc", document["py_document_number"])
        self._text(group, "dFeIniT", issuer.get("timbrado_valid_from"))

    def _build_general_operation(self, parent, payload):
        document = payload["document"]
        group = ET.SubElement(parent, "gDatGralOpe")
        self._text(group, "dFeEmiDE", document["issue_datetime"])
        self._text(group, "iTipEmi", document["py_emission_type"])
        self._text(group, "dCodSeg", document.get("py_cod_seg"))
        self._build_commercial_operation(group, payload)
        self._build_issuer(group, payload)
        self._build_receiver(group, payload)

    def _build_commercial_operation(self, parent, payload):
        operation = payload["operation"]
        group = ET.SubElement(parent, "gOpeCom")
        self._text(group, "iTipTra", operation["transaction_type_code"])
        self._text(group, "dDesTipTra", operation.get("transaction_type_description"))
        self._text(group, "iTImp", operation["tax_type_code"])
        self._text(group, "dDesTImp", operation.get("tax_type_description"))
        self._text(group, "cMoneOpe", operation["currency"])
        self._text(group, "dTiCam", operation.get("exchange_rate"))

    def _build_issuer(self, parent, payload):
        issuer = payload["issuer"]
        group = ET.SubElement(parent, "gEmis")
        self._text(group, "dRucEm", issuer["ruc"])
        self._text(group, "dDVEmi", issuer["ruc_dv"])
        self._text(group, "iTipCont", issuer["taxpayer_type"])
        self._text(group, "dNomEmi", issuer["name"])
        self._text(group, "dDirEmi", issuer.get("address"))
        self._text(group, "dTelEmi", issuer.get("phone"))
        self._text(group, "dEmailE", issuer.get("email"))

    def _build_receiver(self, parent, payload):
        receiver = payload["receiver"]
        group = ET.SubElement(parent, "gDatRec")
        self._text(group, "iNatRec", receiver["nature_code"])
        self._text(group, "iTiOpe", receiver["type_code"])
        self._text(group, "cPaisRec", receiver.get("country_code"))
        self._text(group, "dRucRec", receiver["ruc_or_document"])
        self._text(group, "dDVRec", receiver.get("ruc_dv"))
        self._text(group, "dNomRec", receiver["name"])
        self._text(group, "dDirRec", receiver.get("address"))
        self._text(group, "dTelRec", receiver.get("phone"))
        self._text(group, "dEmailRec", receiver.get("email"))

    def _build_document_type(self, parent, payload):
        group = ET.SubElement(parent, "gDtipDE")
        self._build_condition(group, payload)
        for item in payload["items"]:
            self._build_item(group, item)

    def _build_condition(self, parent, payload):
        condition = payload["condition"]
        group = ET.SubElement(parent, "gCamCond")
        self._text(group, "iCondOpe", condition["sale_condition_code"])
        self._text(group, "dDCondOpe", condition.get("sale_condition_description"))
        payment = ET.SubElement(group, "gPaConEIni")
        self._text(payment, "iTiPago", condition.get("payment_type_code"))
        self._text(payment, "dDesTiPag", condition.get("payment_type_description"))
        self._text(payment, "dMonTiPag", condition.get("payment_amount"))
        self._text(payment, "cMoneTiPag", condition.get("payment_currency"))

    def _build_item(self, parent, item):
        group = ET.SubElement(parent, "gCamItem")
        self._text(group, "dCodInt", item.get("code"))
        self._text(group, "dDesProSer", item["description"])
        self._text(group, "cUniMed", item.get("unit_measure_code"))
        self._text(group, "dDesUniMed", item.get("unit_measure_description"))
        self._text(group, "dCantProSer", item["quantity"])

        values = ET.SubElement(group, "gValorItem")
        self._text(values, "dPUniProSer", item["price_unit"])
        self._text(values, "dDescItem", item.get("discount"))
        self._text(values, "dTotBruOpeItem", item["total"])

        tax = ET.SubElement(group, "gCamIVA")
        self._text(tax, "iAfecIVA", item["tax_affectation"])
        self._text(tax, "dTasaIVA", item.get("tax_rate"))
        self._text(tax, "dPropIVA", item.get("tax_proportion"))
        self._text(tax, "dBasGravIVA", item.get("tax_base"))
        self._text(tax, "dLiqIVAItem", item.get("tax_amount"))
        self._text(tax, "dBasExe", item.get("exempt_base"))

    def _build_totals(self, parent, payload):
        totals = payload["totals"]
        group = ET.SubElement(parent, "gTotSub")
        self._text(group, "dSubExe", totals.get("subtotal_exempt"))
        self._text(group, "dSub5", totals.get("subtotal_5"))
        self._text(group, "dSub10", totals.get("subtotal_10"))
        self._text(group, "dTotOpe", totals.get("total_operation"))
        self._text(group, "dTotDesc", totals.get("total_discount"))
        self._text(group, "dTotIVA5", totals.get("total_vat_5"))
        self._text(group, "dTotIVA10", totals.get("total_vat_10"))
        self._text(group, "dTotIVA", totals.get("total_vat"))
        self._text(group, "dTotGralOpe", totals["total_general"])

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
        self._require(missing, document, "issue_datetime", "issue datetime")
        self._require(missing, document, "py_emission_type", "emission type")
        self._require(missing, issuer, "ruc", "issuer RUC")
        self._require(missing, issuer, "ruc_dv", "issuer RUC DV")
        self._require(missing, issuer, "name", "issuer name")
        self._require(missing, issuer, "taxpayer_type", "issuer taxpayer type")
        self._require(missing, issuer, "establishment_code", "establishment code")
        self._require(missing, issuer, "point_of_issue_code", "point of issue code")
        self._require(missing, issuer, "timbrado_number", "timbrado number")
        self._require(missing, receiver, "name", "receiver name")
        self._require(missing, receiver, "ruc_or_document", "receiver RUC/document")
        self._require(missing, receiver, "nature_code", "receiver nature")
        self._require(missing, receiver, "type_code", "receiver operation type")
        self._require(missing, operation, "transaction_type_code", "transaction type")
        self._require(missing, operation, "tax_type_code", "tax type")
        self._require(missing, operation, "currency", "currency")
        self._require(missing, condition, "sale_condition_code", "sale condition")
        self._require(missing, totals, "total_general", "total general")

        if payload.get("cdc") != document.get("py_cdc"):
            missing.append("payload CDC must match document CDC")
        if not items:
            missing.append("at least one item")
        for index, item in enumerate(items, start=1):
            prefix = f"item {index}"
            self._require(missing, item, "description", f"{prefix} description")
            self._require(missing, item, "quantity", f"{prefix} quantity")
            self._require(missing, item, "price_unit", f"{prefix} price unit")
            self._require(missing, item, "total", f"{prefix} total")
            self._require(missing, item, "tax_affectation", f"{prefix} tax affectation")
            if item.get("tax_affectation") in ("1", "4"):
                self._require(missing, item, "tax_rate", f"{prefix} tax rate")
                self._require(missing, item, "tax_base", f"{prefix} tax base")
                self._require(missing, item, "tax_amount", f"{prefix} tax amount")

        if missing:
            raise ValidationError(
                "Cannot build Paraguay unsigned XML; missing or invalid fields: "
                + "; ".join(missing)
            )

    def _require(self, missing, section, key, label):
        if not self._has_value(section.get(key)):
            missing.append(label)

    def _has_value(self, value):
        return value is not None and value is not False and value != ""

    def _text(self, parent, tag, value):
        if not self._has_value(value):
            return None
        child = ET.SubElement(parent, tag)
        child.text = str(value)
        return child
