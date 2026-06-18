from datetime import datetime, timedelta
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from odoo.tests.common import BaseCase

from odoo.addons.einvoice_py.services.py_certificate_inspection_service import (
    PyCertificateInspectionService,
)


class TestPyCertificateInspectionService(BaseCase):
    PASSWORD = b"fixture-password"
    RUC = "RUC80012345-6"
    INSPECTION_TIME = datetime(2026, 6, 18, 12, 0, 0)

    def setUp(self):
        super().setUp()
        self.service = PyCertificateInspectionService()

    def _key(self, key_size=2048):
        return rsa.generate_private_key(public_exponent=65537, key_size=key_size)

    def _certificate(
        self,
        *,
        key=None,
        subject_ruc=RUC,
        san_rucs=None,
        not_before=None,
        not_after=None,
        digital_signature=True,
        content_commitment=True,
        client_auth=False,
        include_key_usage=True,
        include_basic_constraints=True,
        is_ca=False,
        san_other_rucs=None,
    ):
        key = key or self._key()
        subject_attributes = [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Certificate Fixture"),
        ]
        if subject_ruc is not None:
            subject_attributes.append(
                x509.NameAttribute(NameOID.SERIAL_NUMBER, subject_ruc)
            )
        subject = x509.Name(subject_attributes)
        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(
                not_before or self.INSPECTION_TIME - timedelta(days=1)
            )
            .not_valid_after(
                not_after or self.INSPECTION_TIME + timedelta(days=30)
            )
        )
        if include_basic_constraints:
            builder = builder.add_extension(
                x509.BasicConstraints(ca=is_ca, path_length=None),
                critical=True,
            )
        if include_key_usage:
            builder = builder.add_extension(
                x509.KeyUsage(
                    digital_signature=digital_signature,
                    content_commitment=content_commitment,
                    key_encipherment=True,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=is_ca,
                    crl_sign=is_ca,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
        if client_auth:
            builder = builder.add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=False,
            )
        if san_rucs:
            builder = builder.add_extension(
                x509.SubjectAlternativeName([
                    x509.DirectoryName(x509.Name([
                        x509.NameAttribute(NameOID.SERIAL_NUMBER, ruc)
                    ]))
                    for ruc in san_rucs
                ]),
                critical=False,
            )
        if san_other_rucs:
            builder = builder.add_extension(
                x509.SubjectAlternativeName([
                    x509.OtherName(
                        NameOID.SERIAL_NUMBER,
                        self._der_utf8_string(ruc),
                    )
                    for ruc in san_other_rucs
                ]),
                critical=False,
            )
        return key, builder.sign(private_key=key, algorithm=hashes.SHA256())

    def _der_utf8_string(self, value):
        encoded = value.encode("utf-8")
        return bytes([0x0C, len(encoded)]) + encoded

    def _pkcs12(self, key, certificate, password=PASSWORD):
        return pkcs12.serialize_key_and_certificates(
            name=b"certificate-fixture",
            key=key,
            cert=certificate,
            cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(password),
        )

    def _pem_certificate(self, certificate):
        return certificate.public_bytes(serialization.Encoding.PEM)

    def _pem_key(self, key):
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

    def _inspect_pkcs12(self, bundle, **overrides):
        values = {
            "material_format": "pkcs12",
            "role": "xml_signing",
            "expected_ruc": "80012345-6",
            "inspection_time": self.INSPECTION_TIME,
            "bundle_bytes": bundle,
            "password": self.PASSWORD,
        }
        values.update(overrides)
        return self.service.inspect(**values)

    def _inspect_pem(self, certificate, key=None, **overrides):
        values = {
            "material_format": "pem_pair",
            "role": "xml_signing",
            "expected_ruc": "80012345-6",
            "inspection_time": self.INSPECTION_TIME,
            "certificate_bytes": self._pem_certificate(certificate),
            "private_key_bytes": self._pem_key(key) if key else None,
        }
        values.update(overrides)
        return self.service.inspect(**values)

    def test_valid_password_protected_pkcs12_for_xml_signing_passes(self):
        key, certificate = self._certificate()

        report = self._inspect_pkcs12(self._pkcs12(key, certificate))

        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["public_key_type"], "RSA")
        self.assertEqual(report["public_key_size"], 2048)
        self.assertTrue(report["key_matches_certificate"])
        self.assertEqual(report["extracted_ruc"], self.RUC)
        self.assertEqual(report["ruc_source"], "subject.serialNumber")
        self.assertIn("digitalSignature", report["key_usage"])
        self.assertIn("contentCommitment", report["key_usage"])
        self.assertEqual(len(report["certificate_fingerprint_sha256"]), 64)

    def test_valid_pem_pair_passes(self):
        key, certificate = self._certificate()

        report = self._inspect_pem(certificate, key)

        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["subject"], certificate.subject.rfc4514_string())
        self.assertEqual(report["issuer"], certificate.issuer.rfc4514_string())
        self.assertEqual(
            report["certificate_serial_number"],
            str(certificate.serial_number),
        )

    def test_wrong_pkcs12_password_fails_cleanly(self):
        key, certificate = self._certificate()

        report = self._inspect_pkcs12(
            self._pkcs12(key, certificate),
            password=b"wrong-password",
        )

        self.assertFalse(report["valid"])
        self.assertEqual(
            report["errors"],
            ["Certificate material could not be parsed or decrypted."],
        )

    def test_missing_private_key_fails(self):
        _key, certificate = self._certificate()

        report = self._inspect_pem(certificate)

        self.assertFalse(report["valid"])
        self.assertIn(
            "Certificate material does not contain a private key.",
            report["errors"],
        )

    def test_mismatched_private_key_fails(self):
        _key, certificate = self._certificate()

        report = self._inspect_pem(certificate, self._key())

        self.assertFalse(report["valid"])
        self.assertFalse(report["key_matches_certificate"])
        self.assertIn(
            "Private key does not match the certificate public key.",
            report["errors"],
        )

    def test_expired_certificate_fails(self):
        key, certificate = self._certificate(
            not_before=self.INSPECTION_TIME - timedelta(days=30),
            not_after=self.INSPECTION_TIME - timedelta(seconds=1),
        )

        report = self._inspect_pem(certificate, key)

        self.assertFalse(report["valid"])
        self.assertIn(
            "Certificate is expired at the inspection time.",
            report["errors"],
        )

    def test_not_yet_valid_certificate_fails(self):
        key, certificate = self._certificate(
            not_before=self.INSPECTION_TIME + timedelta(seconds=1),
            not_after=self.INSPECTION_TIME + timedelta(days=30),
        )

        report = self._inspect_pem(certificate, key)

        self.assertFalse(report["valid"])
        self.assertIn(
            "Certificate is not yet valid at the inspection time.",
            report["errors"],
        )

    def test_xml_signing_requires_digital_signature_and_content_commitment(self):
        key, certificate = self._certificate(
            digital_signature=False,
            content_commitment=False,
        )

        report = self._inspect_pem(certificate, key)

        self.assertFalse(report["valid"])
        self.assertIn(
            "XML signing certificate KeyUsage must allow digitalSignature.",
            report["errors"],
        )
        self.assertIn(
            "XML signing certificate KeyUsage must allow contentCommitment.",
            report["errors"],
        )

    def test_xml_signing_requires_key_usage_extension(self):
        key, certificate = self._certificate(include_key_usage=False)

        report = self._inspect_pem(certificate, key)

        self.assertFalse(report["valid"])
        self.assertIn(
            "XML signing certificate must define KeyUsage.",
            report["errors"],
        )

    def test_rsa_key_must_be_at_least_2048_bits(self):
        key, certificate = self._certificate(key=self._key(1024))

        report = self._inspect_pem(certificate, key)

        self.assertFalse(report["valid"])
        self.assertIn(
            "Certificate RSA public key must be at least 2048 bits.",
            report["errors"],
        )
        self.assertIn(
            "Certificate RSA private key must be at least 2048 bits.",
            report["errors"],
        )

    def test_ca_certificate_fails(self):
        key, certificate = self._certificate(is_ca=True)

        report = self._inspect_pem(certificate, key)

        self.assertFalse(report["valid"])
        self.assertIn(
            "Certificate must be an end-entity certificate, not a CA.",
            report["errors"],
        )

    def test_missing_basic_constraints_warns_without_blocking(self):
        key, certificate = self._certificate(include_basic_constraints=False)

        report = self._inspect_pem(certificate, key)

        self.assertTrue(report["valid"], report["errors"])
        self.assertIn(
            "Certificate has no BasicConstraints extension; CA status is unknown.",
            report["warnings"],
        )

    def test_mutual_tls_requires_client_auth(self):
        key, certificate = self._certificate()

        report = self._inspect_pem(
            certificate,
            key,
            role="mutual_tls",
        )

        self.assertFalse(report["valid"])
        self.assertIn(
            "Mutual TLS certificate ExtendedKeyUsage must allow clientAuth.",
            report["errors"],
        )

    def test_mutual_tls_key_usage_requires_digital_signature_when_present(self):
        key, certificate = self._certificate(
            digital_signature=False,
            content_commitment=False,
            client_auth=True,
        )

        report = self._inspect_pem(
            certificate,
            key,
            role="mutual_tls",
        )

        self.assertFalse(report["valid"])
        self.assertIn(
            "Mutual TLS certificate KeyUsage must allow digitalSignature.",
            report["errors"],
        )

    def test_valid_mutual_tls_certificate_passes(self):
        key, certificate = self._certificate(
            content_commitment=False,
            client_auth=True,
        )

        report = self._inspect_pem(
            certificate,
            key,
            role="mutual_tls",
        )

        self.assertTrue(report["valid"], report["errors"])
        self.assertIn("clientAuth", report["extended_key_usage"])

    def test_subject_ruc_extraction_works(self):
        key, certificate = self._certificate()

        report = self._inspect_pem(certificate, key)

        self.assertEqual(report["extracted_ruc"], self.RUC)
        self.assertEqual(report["ruc_source"], "subject.serialNumber")

    def test_san_directory_name_ruc_extraction_works(self):
        key, certificate = self._certificate(
            subject_ruc="PERSON-1234",
            san_rucs=[self.RUC],
        )

        report = self._inspect_pem(certificate, key)

        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["extracted_ruc"], self.RUC)
        self.assertEqual(
            report["ruc_source"],
            "subjectAlternativeName.directoryName.serialNumber",
        )
        self.assertTrue(report["subject_alternative_names"])

    def test_san_other_name_ruc_extraction_works(self):
        key, certificate = self._certificate(
            subject_ruc="PERSON-1234",
            san_other_rucs=[self.RUC],
        )

        report = self._inspect_pem(certificate, key)

        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["extracted_ruc"], self.RUC)
        self.assertEqual(
            report["ruc_source"],
            "subjectAlternativeName.otherName.serialNumber",
        )

    def test_missing_ruc_fails(self):
        key, certificate = self._certificate(subject_ruc=None)

        report = self._inspect_pem(certificate, key)

        self.assertFalse(report["valid"])
        self.assertIn(
            "Certificate does not contain a valid Paraguay RUC identity.",
            report["errors"],
        )

    def test_malformed_ruc_fails(self):
        key, certificate = self._certificate(subject_ruc="RUC80012345")

        report = self._inspect_pem(certificate, key)

        self.assertFalse(report["valid"])
        self.assertIn(
            "Certificate contains a malformed RUC identity value.",
            report["errors"],
        )

    def test_conflicting_ruc_fails(self):
        key, certificate = self._certificate(
            san_rucs=["RUC90012345-7"],
        )

        report = self._inspect_pem(certificate, key)

        self.assertFalse(report["valid"])
        self.assertIn(
            "Certificate contains conflicting Paraguay RUC identities.",
            report["errors"],
        )

    def test_mismatched_expected_ruc_fails(self):
        key, certificate = self._certificate()

        report = self._inspect_pem(
            certificate,
            key,
            expected_ruc="90012345-7",
        )

        self.assertFalse(report["valid"])
        self.assertIn(
            "Certificate Paraguay RUC does not match the expected issuer RUC.",
            report["errors"],
        )

    def test_report_does_not_expose_secret_material(self):
        key, certificate = self._certificate()
        bundle = self._pkcs12(key, certificate)
        private_key_pem = self._pem_key(key)
        certificate_pem = self._pem_certificate(certificate)

        report = self._inspect_pkcs12(bundle)
        serialized_report = repr(report)

        self.assertNotIn(self.PASSWORD.decode(), serialized_report)
        self.assertNotIn("PRIVATE KEY", serialized_report)
        self.assertNotIn(private_key_pem.decode(), serialized_report)
        self.assertNotIn(certificate_pem.decode(), serialized_report)
        self.assertNotIn(repr(bundle), serialized_report)

    def test_extension_inspection_failure_is_sanitized(self):
        key, certificate = self._certificate()

        with patch.object(
            self.service,
            "_subject_alternative_names",
            side_effect=x509.UnsupportedGeneralNameType("unsupported", 999),
        ):
            report = self._inspect_pem(certificate, key)

        self.assertFalse(report["valid"])
        self.assertIn(
            "Certificate metadata or extensions could not be inspected safely.",
            report["errors"],
        )
        self.assertNotIn("unsupported", repr(report))
