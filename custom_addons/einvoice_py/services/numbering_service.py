from odoo.exceptions import ValidationError


class PyNumberingService:
    def __init__(self, env):
        self.env = env

    def find_sequence(
        self,
        document,
        establishment=None,
        point_of_issue=None,
        timbrado=None,
    ):
        establishment = establishment or document.py_establishment_id
        point_of_issue = point_of_issue or document.py_point_of_issue_id
        timbrado = timbrado or document.py_timbrado_id
        return self.env["fiscal.py.sequence"].search(
            [
                ("active", "=", True),
                ("tenant_id", "=", document.tenant_id.id),
                ("company_id", "=", document.company_id.id),
                ("timbrado_id", "=", timbrado.id),
                ("establishment_id", "=", establishment.id),
                ("point_of_issue_id", "=", point_of_issue.id),
                ("document_type", "=", document.document_type),
            ],
            order="id asc",
            limit=1,
        )

    def assign_number(self, document):
        if document.py_document_number and document.py_full_number:
            return document

        sequence = self.find_sequence(document)
        if not sequence:
            raise ValidationError("Active Paraguay sequence is required.")

        self.env.cr.execute(
            """
            SELECT next_number, padding
              FROM fiscal_py_sequence
             WHERE id = %s
             FOR UPDATE
            """,
            [sequence.id],
        )
        next_number, padding = self.env.cr.fetchone()
        document_number = str(next_number).zfill(padding)
        full_number = (
            f"{document.py_establishment_id.code}-"
            f"{document.py_point_of_issue_id.code}-"
            f"{document_number}"
        )

        sequence.write({"next_number": next_number + 1})
        document.with_context(einvoice_skip_fiscal_document_lock=True).write({
            "py_document_number": document_number,
            "py_full_number": full_number,
        })
        return document
