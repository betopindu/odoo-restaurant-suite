import re
from datetime import timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, ExtensionOID, NameOID


class PyCertificateInspectionService:
    """Inspect Paraguay certificate material without retaining secret bytes."""

    MATERIAL_FORMATS = {"pkcs12", "pem_pair"}
    ROLES = {"xml_signing", "mutual_tls"}
    RUC_PATTERN = re.compile(r"^RUC([0-9]+)-([0-9])$")

    def inspect(
        self,
        *,
        material_format,
        role,
        expected_ruc,
        inspection_time,
        bundle_bytes=None,
        certificate_bytes=None,
        private_key_bytes=None,
        password=None,
    ):
        report = self._empty_report()
        errors = report["errors"]
        warnings = report["warnings"]

        if material_format not in self.MATERIAL_FORMATS:
            errors.append("Unsupported certificate material format.")
            return report
        if role not in self.ROLES:
            errors.append("Unsupported certificate role.")
            return report
        if inspection_time is None:
            errors.append("Certificate inspection time is required.")
            return report

        try:
            password_bytes = self._password_bytes(password)
            private_key, certificate, chain = self._load_material(
                material_format=material_format,
                bundle_bytes=bundle_bytes,
                certificate_bytes=certificate_bytes,
                private_key_bytes=private_key_bytes,
                password=password_bytes,
            )
        except (TypeError, ValueError, x509.UnsupportedGeneralNameType):
            errors.append("Certificate material could not be parsed or decrypted.")
            return report

        if certificate is None:
            errors.append("Certificate material does not contain an X.509 certificate.")
            return report

        try:
            self._populate_certificate_report(report, certificate, chain)
            self._validate_certificate_version(errors, certificate)
            self._validate_certificate_public_key(report, certificate)
            self._validate_private_key(report, private_key, certificate)
            self._validate_validity(errors, certificate, inspection_time)
            self._validate_end_entity(errors, warnings, certificate)
            self._validate_role_usage(report, role, certificate)
            self._extract_and_validate_ruc(report, certificate, expected_ruc)
        except (
            TypeError,
            ValueError,
            x509.DuplicateExtension,
            x509.UnsupportedGeneralNameType,
        ):
            errors.append(
                "Certificate metadata or extensions could not be inspected safely."
            )
            return report

        report["valid"] = not errors
        return report

    def _empty_report(self):
        return {
            "valid": False,
            "errors": [],
            "warnings": [],
            "certificate_fingerprint_sha256": None,
            "subject": None,
            "issuer": None,
            "certificate_serial_number": None,
            "not_before": None,
            "not_after": None,
            "public_key_type": None,
            "public_key_size": None,
            "key_matches_certificate": False,
            "key_usage": [],
            "extended_key_usage": [],
            "subject_alternative_names": [],
            "extracted_ruc": None,
            "ruc_source": None,
            "chain_fingerprints": [],
        }

    def _load_material(
        self,
        *,
        material_format,
        bundle_bytes,
        certificate_bytes,
        private_key_bytes,
        password,
    ):
        if material_format == "pkcs12":
            if not bundle_bytes:
                raise ValueError("missing bundle")
            private_key, certificate, chain = pkcs12.load_key_and_certificates(
                bundle_bytes,
                password,
            )
            return private_key, certificate, list(chain or [])

        if not certificate_bytes:
            raise ValueError("missing certificate")
        certificate = x509.load_pem_x509_certificate(certificate_bytes)
        private_key = None
        if private_key_bytes:
            private_key = serialization.load_pem_private_key(
                private_key_bytes,
                password=password,
            )
        return private_key, certificate, []

    def _populate_certificate_report(self, report, certificate, chain):
        public_key = certificate.public_key()
        report.update({
            "certificate_fingerprint_sha256": certificate.fingerprint(
                hashes.SHA256()
            ).hex(),
            "subject": certificate.subject.rfc4514_string(),
            "issuer": certificate.issuer.rfc4514_string(),
            "certificate_serial_number": str(certificate.serial_number),
            "not_before": self._format_datetime(certificate.not_valid_before),
            "not_after": self._format_datetime(certificate.not_valid_after),
            "public_key_type": self._public_key_type(public_key),
            "public_key_size": getattr(public_key, "key_size", None),
            "key_usage": self._key_usage_names(certificate),
            "extended_key_usage": self._extended_key_usage_names(certificate),
            "subject_alternative_names": self._subject_alternative_names(certificate),
            "chain_fingerprints": [
                item.fingerprint(hashes.SHA256()).hex()
                for item in chain
            ],
        })

    def _validate_certificate_version(self, errors, certificate):
        if certificate.version != x509.Version.v3:
            errors.append("Certificate must use X.509 version 3.")

    def _validate_certificate_public_key(self, report, certificate):
        public_key = certificate.public_key()
        if not isinstance(public_key, rsa.RSAPublicKey):
            report["errors"].append("Certificate public key must be RSA.")
            return
        if public_key.key_size < 2048:
            report["errors"].append(
                "Certificate RSA public key must be at least 2048 bits."
            )

    def _validate_private_key(self, report, private_key, certificate):
        errors = report["errors"]
        if private_key is None:
            errors.append("Certificate material does not contain a private key.")
            return
        if not isinstance(private_key, rsa.RSAPrivateKey):
            errors.append("Certificate private key must be RSA.")
            return

        if private_key.key_size < 2048:
            errors.append("Certificate RSA private key must be at least 2048 bits.")

        certificate_public_bytes = certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        private_public_bytes = private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        report["key_matches_certificate"] = (
            certificate_public_bytes == private_public_bytes
        )
        if not report["key_matches_certificate"]:
            errors.append("Private key does not match the certificate public key.")

    def _validate_validity(self, errors, certificate, inspection_time):
        normalized_time = self._normalize_datetime(inspection_time)
        if normalized_time < certificate.not_valid_before:
            errors.append("Certificate is not yet valid at the inspection time.")
        if normalized_time > certificate.not_valid_after:
            errors.append("Certificate is expired at the inspection time.")

    def _validate_end_entity(self, errors, warnings, certificate):
        try:
            constraints = certificate.extensions.get_extension_for_oid(
                ExtensionOID.BASIC_CONSTRAINTS
            ).value
        except x509.ExtensionNotFound:
            warnings.append(
                "Certificate has no BasicConstraints extension; CA status is unknown."
            )
            return
        if constraints.ca:
            errors.append("Certificate must be an end-entity certificate, not a CA.")

    def _validate_role_usage(self, report, role, certificate):
        errors = report["errors"]
        try:
            key_usage = certificate.extensions.get_extension_for_oid(
                ExtensionOID.KEY_USAGE
            ).value
        except x509.ExtensionNotFound:
            key_usage = None

        if role == "xml_signing":
            if key_usage is None:
                errors.append("XML signing certificate must define KeyUsage.")
                return
            if not key_usage.digital_signature:
                errors.append(
                    "XML signing certificate KeyUsage must allow digitalSignature."
                )
            if not key_usage.content_commitment:
                errors.append(
                    "XML signing certificate KeyUsage must allow contentCommitment."
                )
            return

        if key_usage is not None and not key_usage.digital_signature:
            errors.append(
                "Mutual TLS certificate KeyUsage must allow digitalSignature."
            )
        try:
            extended_usage = certificate.extensions.get_extension_for_oid(
                ExtensionOID.EXTENDED_KEY_USAGE
            ).value
        except x509.ExtensionNotFound:
            extended_usage = ()
        if ExtendedKeyUsageOID.CLIENT_AUTH not in extended_usage:
            errors.append(
                "Mutual TLS certificate ExtendedKeyUsage must allow clientAuth."
            )

    def _extract_and_validate_ruc(self, report, certificate, expected_ruc):
        candidates = []
        malformed = []

        for attribute in certificate.subject.get_attributes_for_oid(
            NameOID.SERIAL_NUMBER
        ):
            self._collect_ruc_candidate(
                candidates,
                malformed,
                attribute.value,
                "subject.serialNumber",
            )

        try:
            san = certificate.extensions.get_extension_for_oid(
                ExtensionOID.SUBJECT_ALTERNATIVE_NAME
            ).value
        except x509.ExtensionNotFound:
            san = ()

        for name in san:
            if isinstance(name, x509.DirectoryName):
                for attribute in name.value.get_attributes_for_oid(
                    NameOID.SERIAL_NUMBER
                ):
                    self._collect_ruc_candidate(
                        candidates,
                        malformed,
                        attribute.value,
                        "subjectAlternativeName.directoryName.serialNumber",
                    )
            elif (
                isinstance(name, x509.OtherName)
                and name.type_id == NameOID.SERIAL_NUMBER
            ):
                decoded = self._decode_der_string(name.value)
                if decoded is None:
                    malformed.append(
                        "subjectAlternativeName.otherName.serialNumber"
                    )
                else:
                    self._collect_ruc_candidate(
                        candidates,
                        malformed,
                        decoded,
                        "subjectAlternativeName.otherName.serialNumber",
                    )

        errors = report["errors"]
        if malformed:
            errors.append("Certificate contains a malformed RUC identity value.")

        unique_values = {}
        for value, source in candidates:
            unique_values.setdefault(value, []).append(source)

        if not unique_values:
            errors.append("Certificate does not contain a valid Paraguay RUC identity.")
            return
        if len(unique_values) > 1:
            errors.append("Certificate contains conflicting Paraguay RUC identities.")
            return

        extracted_ruc, sources = next(iter(unique_values.items()))
        report["extracted_ruc"] = extracted_ruc
        report["ruc_source"] = sources[0]

        normalized_expected = self._normalize_expected_ruc(expected_ruc)
        if normalized_expected is None:
            errors.append("Expected Paraguay RUC is missing or malformed.")
        elif extracted_ruc != normalized_expected:
            errors.append("Certificate Paraguay RUC does not match the expected issuer RUC.")

    def _collect_ruc_candidate(self, candidates, malformed, value, source):
        normalized = str(value).strip().upper()
        match = self.RUC_PATTERN.fullmatch(normalized)
        if not match:
            if normalized.startswith("RUC"):
                malformed.append(source)
            return
        candidates.append((f"RUC{match.group(1)}-{match.group(2)}", source))

    def _normalize_expected_ruc(self, expected_ruc):
        if expected_ruc is None:
            return None
        normalized = str(expected_ruc).strip().upper()
        if not normalized.startswith("RUC"):
            normalized = f"RUC{normalized}"
        match = self.RUC_PATTERN.fullmatch(normalized)
        if not match:
            return None
        return f"RUC{match.group(1)}-{match.group(2)}"

    def _key_usage_names(self, certificate):
        try:
            usage = certificate.extensions.get_extension_for_oid(
                ExtensionOID.KEY_USAGE
            ).value
        except x509.ExtensionNotFound:
            return []
        names = []
        for attribute, label in (
            ("digital_signature", "digitalSignature"),
            ("content_commitment", "contentCommitment"),
            ("key_encipherment", "keyEncipherment"),
            ("data_encipherment", "dataEncipherment"),
            ("key_agreement", "keyAgreement"),
            ("key_cert_sign", "keyCertSign"),
            ("crl_sign", "cRLSign"),
        ):
            if getattr(usage, attribute):
                names.append(label)
        if usage.key_agreement:
            if usage.encipher_only:
                names.append("encipherOnly")
            if usage.decipher_only:
                names.append("decipherOnly")
        return names

    def _extended_key_usage_names(self, certificate):
        try:
            usage = certificate.extensions.get_extension_for_oid(
                ExtensionOID.EXTENDED_KEY_USAGE
            ).value
        except x509.ExtensionNotFound:
            return []
        names = []
        for oid in usage:
            if oid == ExtendedKeyUsageOID.CLIENT_AUTH:
                names.append("clientAuth")
            else:
                names.append(oid.dotted_string)
        return names

    def _subject_alternative_names(self, certificate):
        try:
            names = certificate.extensions.get_extension_for_oid(
                ExtensionOID.SUBJECT_ALTERNATIVE_NAME
            ).value
        except x509.ExtensionNotFound:
            return []

        values = []
        for name in names:
            if isinstance(name, x509.DirectoryName):
                values.append(f"directoryName:{name.value.rfc4514_string()}")
            elif isinstance(name, x509.OtherName):
                decoded = self._decode_der_string(name.value)
                display = decoded if decoded is not None else "<unsupported DER value>"
                values.append(f"otherName:{name.type_id.dotted_string}:{display}")
            else:
                values.append(f"{name.__class__.__name__}:{name.value}")
        return values

    def _decode_der_string(self, value):
        if not isinstance(value, bytes) or len(value) < 2:
            return None
        tag = value[0]
        if tag not in {0x0C, 0x13, 0x16}:
            return None
        length_byte = value[1]
        offset = 2
        if length_byte & 0x80:
            length_size = length_byte & 0x7F
            if length_size == 0 or len(value) < offset + length_size:
                return None
            length = int.from_bytes(value[offset:offset + length_size], "big")
            offset += length_size
        else:
            length = length_byte
        payload = value[offset:offset + length]
        if len(payload) != length or offset + length != len(value):
            return None
        encoding = "utf-8" if tag == 0x0C else "ascii"
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            return None

    def _public_key_type(self, public_key):
        if isinstance(public_key, rsa.RSAPublicKey):
            return "RSA"
        return public_key.__class__.__name__

    def _normalize_datetime(self, value):
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def _format_datetime(self, value):
        return f"{value.isoformat()}Z"

    def _password_bytes(self, password):
        if password is None or isinstance(password, bytes):
            return password
        if isinstance(password, str):
            return password.encode("utf-8")
        raise TypeError("invalid password")
