import secrets

from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_sifen_datetime_service import (
    PySifenDatetimeService,
)


class PyCdcService:
    DOCUMENT_TYPE_CODES = {
        "invoice": "01",
        "self_invoice": "04",
        "credit_note": "05",
        "debit_note": "06",
        "remission_note": "07",
    }

    def __init__(self, env):
        self.env = env

    def validation_errors(
        self,
        document,
        establishment=None,
        point_of_issue=None,
        issuer=None,
        require_document_number=True,
    ):
        establishment = establishment or document.py_establishment_id
        point_of_issue = point_of_issue or document.py_point_of_issue_id
        issuer = issuer or document.py_issuer_id
        issuer_ruc = document.py_issuer_ruc or issuer.ruc
        issuer_ruc_dv = document.py_issuer_ruc_dv or issuer.ruc_dv
        issuer_taxpayer_type = document.py_issuer_taxpayer_type or issuer.taxpayer_type
        errors = []

        if document.document_type not in self.DOCUMENT_TYPE_CODES:
            errors.append(
                f"Unsupported Paraguay CDC document type: {document.document_type}."
            )
        if not issuer_ruc:
            errors.append("Paraguay CDC issuer RUC is required.")
        elif not issuer_ruc.isdigit() or len(issuer_ruc) > 8:
            errors.append("Paraguay CDC issuer RUC must be numeric and at most 8 digits.")
        if not issuer_ruc_dv:
            errors.append("Paraguay CDC issuer RUC DV is required.")
        elif not issuer_ruc_dv.isdigit() or len(issuer_ruc_dv) != 1:
            errors.append("Paraguay CDC issuer RUC DV must be exactly 1 digit.")
        if issuer_taxpayer_type not in ("1", "2"):
            errors.append("Paraguay CDC issuer taxpayer type is required.")
        if not establishment or not establishment.code:
            errors.append("Paraguay CDC establishment code is required.")
        elif not establishment.code.isdigit() or len(establishment.code) != 3:
            errors.append("Paraguay CDC establishment code must be exactly 3 digits.")
        if not point_of_issue or not point_of_issue.code:
            errors.append("Paraguay CDC point of issue code is required.")
        elif not point_of_issue.code.isdigit() or len(point_of_issue.code) != 3:
            errors.append("Paraguay CDC point of issue code must be exactly 3 digits.")
        if require_document_number:
            if not document.py_document_number:
                errors.append("Paraguay CDC document number is required.")
            elif (
                not document.py_document_number.isdigit()
                or len(document.py_document_number) != 7
            ):
                errors.append("Paraguay CDC document number must be exactly 7 digits.")
        if not document.issue_datetime:
            errors.append("Paraguay CDC issue datetime is required.")
        if document.py_emission_type not in ("1", "2"):
            errors.append("Paraguay CDC emission type is required.")
        if document.py_cod_seg and (
            not document.py_cod_seg.isdigit() or len(document.py_cod_seg) != 9
        ):
            errors.append("Paraguay CDC security code must be exactly 9 digits.")

        return errors

    def generate(self, document):
        if document.py_cdc:
            return document.py_cdc

        errors = self.validation_errors(document)
        if errors:
            raise ValidationError("; ".join(errors))

        cod_seg = document.py_cod_seg or self._generate_cod_seg()
        base = self._compose_base(document, cod_seg)
        dv, total, remainder = self.calculate_check_digit(base)
        cdc = f"{base}{dv}"
        if len(base) != 43 or len(cdc) != 44:
            raise ValidationError("Generated Paraguay CDC has an invalid length.")

        document.with_context(einvoice_skip_fiscal_document_lock=True).write({
            "py_cod_seg": cod_seg,
            "py_cdc_base": base,
            "py_cdc_dv": str(dv),
            "py_cdc": cdc,
            "country_identifier": cdc,
        })
        return cdc

    def _compose_base(self, document, cod_seg):
        issue_date = PySifenDatetimeService.format_fiscal_datetime(
            document.issue_datetime,
            field_label="Paraguay CDC emission timestamp",
        )[:10].replace("-", "")
        return "".join(
            [
                self.DOCUMENT_TYPE_CODES[document.document_type],
                document.py_issuer_ruc.zfill(8),
                document.py_issuer_ruc_dv,
                document.py_establishment_id.code,
                document.py_point_of_issue_id.code,
                document.py_document_number,
                document.py_issuer_taxpayer_type,
                issue_date,
                document.py_emission_type,
                cod_seg,
            ]
        )

    def _generate_cod_seg(self):
        return f"{secrets.randbelow(1_000_000_000):09d}"

    @classmethod
    def calculate_check_digit(cls, value):
        factor = 2
        total = 0
        for char in reversed(value):
            total += int(char) * factor
            factor += 1
            if factor > 11:
                factor = 2
        remainder = total % 11
        digit = 11 - remainder if remainder > 1 else 0
        return digit, total, remainder
