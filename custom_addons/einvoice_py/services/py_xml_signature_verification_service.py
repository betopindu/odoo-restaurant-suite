import base64
import hashlib

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from lxml import etree

from odoo.addons.einvoice_py.services.py_unsigned_xml_builder import (
    PyUnsignedXmlBuilder,
)
from odoo.addons.einvoice_py.services.py_xml_signature_service import (
    PyXmlSignatureService,
)

try:
    import xmlsec
except ImportError:  # pragma: no cover - exercised by runtime dependency tests
    xmlsec = None


class PyXmlSignatureVerificationService:
    """Verify signed Paraguay XML locally without trust-chain or revocation checks."""

    SIFEN_NS = PyUnsignedXmlBuilder.SIFEN_NS
    XMLDSIG_NS = PyXmlSignatureService.XMLDSIG_NS
    EXPECTED_CANONICALIZATION_METHOD = (
        "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
    )
    EXPECTED_SIGNATURE_METHOD = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
    EXPECTED_DIGEST_METHOD = "http://www.w3.org/2001/04/xmlenc#sha256"
    EXPECTED_TRANSFORMS = [
        "http://www.w3.org/2000/09/xmldsig#enveloped-signature",
        "http://www.w3.org/2001/10/xml-exc-c14n#",
    ]

    def verify(
        self,
        *,
        signed_xml_bytes,
        expected_cdc=None,
        expected_certificate_fingerprint=None,
    ):
        report = self._empty_report()
        if xmlsec is None:
            report["errors"].append("XML security runtime is not available.")
            return self._finalize(report)

        root = self._parse(signed_xml_bytes, report)
        if root is None:
            return self._finalize(report)

        de = self._validate_structure(root, report)
        signature = self._locate_signature(root, de, report) if de is not None else None
        if de is None or signature is None:
            return self._finalize(report)

        cdc = (de.get("Id") or "").strip()
        report["cdc"] = cdc or None
        if not cdc:
            report["errors"].append("Signed Paraguay XML DE is missing Id.")
        if expected_cdc and cdc != expected_cdc:
            report["errors"].append("Signed Paraguay XML CDC does not match expected CDC.")

        self._populate_signature_metadata(signature, report)
        if report["reference_uri"] != f"#{cdc}":
            report["errors"].append(
                "Signed Paraguay XML Reference URI must match DE CDC."
            )
        if not self._algorithms_are_supported(report):
            report["errors"].append("Signed Paraguay XML uses unsupported algorithms.")

        certificate = self._extract_certificate(signature, report)
        if certificate is not None:
            fingerprint = self._certificate_fingerprint(certificate)
            report["certificate_fingerprint_sha256"] = fingerprint
            if (
                expected_certificate_fingerprint
                and fingerprint.lower() != expected_certificate_fingerprint.lower()
            ):
                report["errors"].append(
                    "Signed Paraguay XML certificate fingerprint does not match expected fingerprint."
                )

        if not report["errors"]:
            self._verify_signature(root, signature, certificate, report)
        return self._finalize(report)

    def _empty_report(self):
        return {
            "valid": False,
            "errors": [],
            "warnings": [],
            "cdc": None,
            "reference_uri": None,
            "digest_value": None,
            "certificate_fingerprint_sha256": None,
            "signature_method": None,
            "digest_method": None,
            "canonicalization_method": None,
            "transforms": [],
        }

    def _parse(self, xml_content, report):
        try:
            if isinstance(xml_content, str):
                xml_content = xml_content.encode("utf-8")
            parser = etree.XMLParser(
                resolve_entities=False,
                load_dtd=False,
                no_network=True,
            )
            return etree.fromstring(xml_content, parser=parser)
        except (TypeError, ValueError, etree.XMLSyntaxError):
            report["errors"].append("Malformed signed Paraguay XML.")
            return None

    def _validate_structure(self, root, report):
        if root.tag != self._tag("rDE"):
            report["errors"].append(
                "Signed Paraguay XML root must be rDE in the official SIFEN namespace."
            )

        de_nodes = root.findall(self._tag("DE"))
        if len(de_nodes) != 1:
            report["errors"].append("Signed Paraguay XML must contain exactly one DE.")
            return None
        return de_nodes[0]

    def _locate_signature(self, root, de, report):
        signature_nodes = root.xpath(".//*[local-name()='Signature']")
        if len(signature_nodes) != 1:
            report["errors"].append(
                "Signed Paraguay XML must contain exactly one Signature."
            )
            return None

        signature = signature_nodes[0]
        children = list(root)
        if signature.getparent() is not root:
            report["errors"].append("Signed Paraguay XML Signature must be under rDE.")
            return None
        if children.index(signature) <= children.index(de):
            report["errors"].append("Signed Paraguay XML Signature must be after DE.")
            return None
        return signature

    def _populate_signature_metadata(self, signature, report):
        reference = signature.find(f".//{{{self.XMLDSIG_NS}}}Reference")
        if reference is not None:
            report["reference_uri"] = reference.get("URI")

        digest_value = signature.find(f".//{{{self.XMLDSIG_NS}}}DigestValue")
        if digest_value is not None:
            report["digest_value"] = (digest_value.text or "").strip() or None

        canonicalization_method = signature.find(
            f".//{{{self.XMLDSIG_NS}}}CanonicalizationMethod"
        )
        if canonicalization_method is not None:
            report["canonicalization_method"] = canonicalization_method.get("Algorithm")

        signature_method = signature.find(f".//{{{self.XMLDSIG_NS}}}SignatureMethod")
        if signature_method is not None:
            report["signature_method"] = signature_method.get("Algorithm")

        digest_method = signature.find(f".//{{{self.XMLDSIG_NS}}}DigestMethod")
        if digest_method is not None:
            report["digest_method"] = digest_method.get("Algorithm")

        report["transforms"] = [
            transform.get("Algorithm")
            for transform in signature.findall(f".//{{{self.XMLDSIG_NS}}}Transform")
        ]

    def _algorithms_are_supported(self, report):
        return (
            report["canonicalization_method"] == self.EXPECTED_CANONICALIZATION_METHOD
            and report["signature_method"] == self.EXPECTED_SIGNATURE_METHOD
            and report["digest_method"] == self.EXPECTED_DIGEST_METHOD
            and report["transforms"] == self.EXPECTED_TRANSFORMS
        )

    def _extract_certificate(self, signature, report):
        node = signature.find(f".//{{{self.XMLDSIG_NS}}}X509Certificate")
        if node is None or not (node.text or "").strip():
            report["errors"].append("Signed Paraguay XML is missing X509Certificate.")
            return None
        try:
            certificate_der = base64.b64decode("".join((node.text or "").split()))
            return x509.load_der_x509_certificate(certificate_der)
        except (TypeError, ValueError):
            report["errors"].append("Signed Paraguay XML X509Certificate is invalid.")
            return None

    def _certificate_fingerprint(self, certificate):
        certificate_der = certificate.public_bytes(serialization.Encoding.DER)
        return hashlib.sha256(certificate_der).hexdigest()

    def _verify_signature(self, root, signature, certificate, report):
        try:
            xmlsec.tree.add_ids(root, ["Id"])
            certificate_pem = certificate.public_bytes(serialization.Encoding.PEM)
            key = xmlsec.Key.from_memory(
                certificate_pem,
                xmlsec.constants.KeyDataFormatCertPem,
            )
            context = xmlsec.SignatureContext()
            context.key = key
            context.verify(signature)
        except (TypeError, ValueError, xmlsec.Error):
            report["errors"].append("Signed Paraguay XML cryptographic verification failed.")

    def _finalize(self, report):
        report["valid"] = not report["errors"]
        return report

    def _tag(self, name):
        return f"{{{self.SIFEN_NS}}}{name}"
