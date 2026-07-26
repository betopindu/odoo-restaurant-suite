from odoo.exceptions import ValidationError

from odoo.addons.einvoice_py.services.py_signed_xml_attachment_service import (
    PySignedXmlAttachmentService,
)
from odoo.addons.einvoice_py.services.py_signed_xml_preparation_service import (
    PySignedXmlPreparationService,
)
from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)
from odoo.addons.einvoice_py.services.py_xml_signature_service import (
    PyXmlSignatureService,
)
from odoo.addons.einvoice_py.services.py_xml_signature_verification_service import (
    PyXmlSignatureVerificationService,
)


class PySigningPipelineService:
    """Coordinate the Paraguay signing pipeline without duplicating stage logic."""

    def __init__(self, env):
        self.env = env

    def sign(
        self,
        *,
        document,
        payload,
        certificate_bytes,
        private_key_bytes,
        signing_timestamp,
        private_key_password=None,
        filename=None,
    ):
        document.ensure_one()
        unsigned_xml_bytes = PyUnsignedXmlBuilder(self.env).build_from_payload(payload)
        preparation_result = PySignedXmlPreparationService().prepare(
            document,
            unsigned_xml_bytes,
            signing_timestamp,
        )
        signature_result = PyXmlSignatureService().sign(
            prepared_xml_bytes=preparation_result["prepared_xml_bytes"],
            certificate_bytes=certificate_bytes,
            private_key_bytes=private_key_bytes,
            private_key_password=private_key_password,
            cdc=preparation_result["cdc"],
        )
        verification_result = PyXmlSignatureVerificationService().verify(
            signed_xml_bytes=signature_result["signed_xml_bytes"],
            expected_cdc=preparation_result["cdc"],
        )
        if not verification_result["valid"]:
            raise ValidationError(
                "Signed Paraguay XML failed local verification: "
                + "; ".join(verification_result["errors"])
            )

        attachment = PySignedXmlAttachmentService(self.env).persist(
            document=document,
            signed_xml_bytes=signature_result["signed_xml_bytes"],
            filename=filename or f"{document.uuid}-paraguay-signed.xml",
            metadata={
                "cdc": preparation_result["cdc"],
                "digest_value": verification_result.get("digest_value"),
                "certificate_fingerprint_sha256": verification_result.get(
                    "certificate_fingerprint_sha256"
                ),
                "signing_time": preparation_result.get("signing_time"),
            },
        )
        return {
            "cdc": preparation_result["cdc"],
            "digest_value": verification_result.get("digest_value"),
            "certificate_fingerprint_sha256": verification_result.get(
                "certificate_fingerprint_sha256"
            ),
            "signed_attachment_id": attachment.id,
            "verification_result": verification_result,
        }
