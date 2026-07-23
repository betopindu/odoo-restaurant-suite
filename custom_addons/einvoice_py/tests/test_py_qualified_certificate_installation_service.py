import json
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_qualified_certificate_installation_service import (
    PyQualifiedCertificateInstallationValidationService,
)


class TestPyQualifiedCertificateInstallationValidationService(TransactionCase):
    PASSWORD = b"synthetic-installation-password"
    RUC = "RUC80012345-6"
    INSPECTION_TIME = datetime(2026, 7, 24, 12, 0, 0)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.tenant = cls.env["fiscal.tenant"].create({
            "name": "Qualified Certificate Installation Tenant",
            "code": "qualified-certificate-installation",
            "company_id": cls.company.id,
        })

    def _key(self):
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def _certificate(
        self,
        *,
        ruc=RUC,
        not_before=None,
        not_after=None,
        is_ca=False,
        digital_signature=True,
        content_commitment=True,
        client_auth=True,
    ):
        key = self._key()
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PY"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Installation Fixture"),
            x509.NameAttribute(NameOID.SERIAL_NUMBER, ruc),
        ])
        certificate = (
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
            .add_extension(
                x509.BasicConstraints(ca=is_ca, path_length=None),
                critical=True,
            )
            .add_extension(
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
            .add_extension(
                x509.ExtendedKeyUsage(
                    [ExtendedKeyUsageOID.CLIENT_AUTH] if client_auth else []
                ),
                critical=False,
            )
            .sign(private_key=key, algorithm=hashes.SHA256())
        )
        return key, certificate

    def _pkcs12(self, key, certificate):
        return pkcs12.serialize_key_and_certificates(
            name=b"synthetic-installation-fixture",
            key=key,
            cert=certificate,
            cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(
                self.PASSWORD
            ),
        )

    def _certificate_only_pkcs12(self, certificate):
        return pkcs12.serialize_key_and_certificates(
            name=b"synthetic-certificate-only-fixture",
            key=None,
            cert=certificate,
            cas=None,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def _secret_file(self, contents):
        secret_file = tempfile.NamedTemporaryFile()
        secret_file.write(contents)
        secret_file.flush()
        self.addCleanup(secret_file.close)
        return secret_file

    def _configuration(self, bundle, *, password_reference=None):
        bundle_file = self._secret_file(bundle)
        if password_reference is None:
            password_file = self._secret_file(self.PASSWORD + b"\n")
            password_reference = f"file://{password_file.name}"
        credential = self.env["fiscal.credential"].create({
            "name": "Synthetic Qualified Certificate",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "provider_type": "external_secret",
            "material_format": "pkcs12",
            "secret_ref": f"file://{bundle_file.name}",
            "password_secret_ref": password_reference,
        })
        adapter = self.env["fiscal.adapter.config"].create({
            "name": "Paraguay Qualified Certificate Adapter",
            "tenant_id": self.tenant.id,
            "company_id": self.company.id,
            "country_code": "PY",
            "adapter_code": "py",
            "environment": "test",
            "credentials_mode": "external_secret",
        })
        for role in ("xml_signing", "mutual_tls"):
            self.env["fiscal.adapter.credential.binding"].create({
                "adapter_config_id": adapter.id,
                "credential_id": credential.id,
                "role": role,
            })
        return credential, adapter, bundle_file

    def _validate(self, credential, adapter, **overrides):
        values = {
            "credential": credential,
            "adapter_config": adapter,
            "expected_ruc": "80012345-6",
            "inspection_time": self.INSPECTION_TIME,
        }
        values.update(overrides)
        return PyQualifiedCertificateInstallationValidationService(
            self.env
        ).validate(**values)

    def test_valid_pkcs12_and_shared_role_bindings_pass(self):
        key, certificate = self._certificate()
        credential, adapter, _bundle_file = self._configuration(
            self._pkcs12(key, certificate)
        )

        report = self._validate(credential, adapter)

        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["status"], "valid")
        self.assertEqual(set(report["roles"]), {"xml_signing", "mutual_tls"})
        self.assertTrue(
            report["roles"]["xml_signing"]["key_matches_certificate"]
        )
        self.assertIn(
            "digitalSignature",
            report["roles"]["xml_signing"]["key_usage"],
        )
        self.assertIn(
            "contentCommitment",
            report["roles"]["xml_signing"]["key_usage"],
        )
        self.assertIn(
            "clientAuth",
            report["roles"]["mutual_tls"]["extended_key_usage"],
        )
        self.assertEqual(
            adapter.credential_binding_ids.mapped("credential_id"),
            credential,
        )
        self.assertEqual(credential.inspection_status, "valid")
        self.assertEqual(credential.extracted_ruc, self.RUC)

    def test_environment_password_reference_passes(self):
        key, certificate = self._certificate()
        credential, adapter, _bundle_file = self._configuration(
            self._pkcs12(key, certificate),
            password_reference="env://SYNTHETIC_INSTALLATION_PASSWORD",
        )

        with patch.dict(
            os.environ,
            {"SYNTHETIC_INSTALLATION_PASSWORD": self.PASSWORD.decode()},
        ):
            report = self._validate(credential, adapter)

        self.assertTrue(report["valid"], report["errors"])

    def test_wrong_password_fails_without_secret_disclosure(self):
        key, certificate = self._certificate()
        bundle = self._pkcs12(key, certificate)
        credential, adapter, bundle_file = self._configuration(
            bundle,
            password_reference="env://SENSITIVE_PASSWORD_VARIABLE",
        )

        with patch.dict(
            os.environ,
            {"SENSITIVE_PASSWORD_VARIABLE": "wrong-secret-password"},
        ):
            report = self._validate(credential, adapter)

        serialized = json.dumps(report, sort_keys=True)
        persisted = credential.inspection_report_json
        self.assertFalse(report["valid"])
        self.assertEqual(report["status"], "invalid")
        self.assertIn(
            "Certificate material could not be parsed or decrypted.",
            serialized,
        )
        for forbidden in (
            "wrong-secret-password",
            self.PASSWORD.decode(),
            bundle_file.name,
            "SENSITIVE_PASSWORD_VARIABLE",
            repr(bundle),
        ):
            self.assertNotIn(forbidden, serialized)
            self.assertNotIn(forbidden, persisted)

    def test_wrong_ruc_is_invalid(self):
        key, certificate = self._certificate()
        credential, adapter, _bundle_file = self._configuration(
            self._pkcs12(key, certificate)
        )

        report = self._validate(
            credential,
            adapter,
            expected_ruc="90012345-7",
        )

        self.assertFalse(report["valid"])
        self.assertIn(
            "xml_signing: Certificate Paraguay RUC does not match the expected issuer RUC.",
            report["errors"],
        )

    def test_expired_certificate_is_invalid(self):
        key, certificate = self._certificate(
            not_before=self.INSPECTION_TIME - timedelta(days=30),
            not_after=self.INSPECTION_TIME - timedelta(days=1),
        )
        credential, adapter, _bundle_file = self._configuration(
            self._pkcs12(key, certificate)
        )

        report = self._validate(credential, adapter)

        self.assertFalse(report["valid"])
        self.assertIn(
            "xml_signing: Certificate is expired at the inspection time.",
            report["errors"],
        )

    def test_ca_certificate_is_invalid(self):
        key, certificate = self._certificate(is_ca=True)
        credential, adapter, _bundle_file = self._configuration(
            self._pkcs12(key, certificate)
        )

        report = self._validate(credential, adapter)

        self.assertFalse(report["valid"])
        self.assertIn(
            "xml_signing: Certificate must be an end-entity certificate, not a CA.",
            report["errors"],
        )

    def test_pkcs12_without_certificate_key_pair_is_invalid(self):
        _key, certificate = self._certificate()
        credential, adapter, _bundle_file = self._configuration(
            self._certificate_only_pkcs12(certificate),
            password_reference=False,
        )

        report = self._validate(credential, adapter)

        self.assertFalse(report["valid"])
        self.assertIn(
            "xml_signing: Certificate material does not contain an X.509 certificate.",
            report["errors"],
        )

    def test_missing_required_usages_is_invalid_for_both_roles(self):
        key, certificate = self._certificate(
            digital_signature=False,
            content_commitment=False,
            client_auth=False,
        )
        credential, adapter, _bundle_file = self._configuration(
            self._pkcs12(key, certificate)
        )

        report = self._validate(credential, adapter)

        self.assertFalse(report["valid"])
        self.assertIn(
            "xml_signing: XML signing certificate KeyUsage must allow digitalSignature.",
            report["errors"],
        )
        self.assertIn(
            "xml_signing: XML signing certificate KeyUsage must allow contentCommitment.",
            report["errors"],
        )
        self.assertIn(
            "mutual_tls: Mutual TLS certificate KeyUsage must allow digitalSignature.",
            report["errors"],
        )
        self.assertIn(
            "mutual_tls: Mutual TLS certificate ExtendedKeyUsage must allow clientAuth.",
            report["errors"],
        )

    def test_missing_binding_fails_before_material_load(self):
        key, certificate = self._certificate()
        credential, adapter, bundle_file = self._configuration(
            self._pkcs12(key, certificate)
        )
        adapter.credential_binding_ids.filtered(
            lambda binding: binding.role == "mutual_tls"
        ).unlink()
        bundle_file.close()

        report = self._validate(credential, adapter)

        self.assertFalse(report["valid"])
        self.assertEqual(report["status"], "invalid")
        self.assertIn(
            "Qualified certificate must be bound once to mutual_tls.",
            report["errors"],
        )

    def test_provider_failure_is_safe_and_persists_no_material(self):
        key, certificate = self._certificate()
        bundle = self._pkcs12(key, certificate)
        credential, adapter, bundle_file = self._configuration(bundle)
        full_path = bundle_file.name
        bundle_file.close()

        report = self._validate(credential, adapter)

        serialized = json.dumps(report, sort_keys=True)
        persisted = credential.inspection_report_json
        self.assertFalse(report["valid"])
        self.assertEqual(report["status"], "error")
        self.assertEqual(
            report["errors"],
            ["Qualified certificate material could not be loaded."],
        )
        for forbidden in (full_path, repr(bundle), self.PASSWORD.decode()):
            self.assertNotIn(forbidden, serialized)
            self.assertNotIn(forbidden, persisted)
