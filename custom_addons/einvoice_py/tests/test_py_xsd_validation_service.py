import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_xsd_validation_service import PyXsdValidationService


class TestPyXsdValidationService(TransactionCase):
    COMPLETE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd"
     xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
  <dVerFor>150</dVerFor>
  <DE Id="01234567890123456789012345678901234567890123">
    <dFecFirma>2026-06-18T12:34:56</dFecFirma>
  </DE>
  <ds:Signature>
    <ds:SignedInfo>
      <ds:Reference URI="#01234567890123456789012345678901234567890123">
        <ds:DigestValue>digest-fixture</ds:DigestValue>
      </ds:Reference>
    </ds:SignedInfo>
  </ds:Signature>
  <gCamFuFD>
    <dCarQR>https://example.test/qr?nVersion=150&amp;Id=01234567890123456789012345678901234567890123&amp;cHashQR=abc</dCarQR>
  </gCamFuFD>
</rDE>
"""

    def _write_manifest(self, root_dir, values):
        path = Path(root_dir) / "manifest.json"
        path.write_text(json.dumps(values), encoding="utf-8")
        return path

    def _write_xsd_file(self, root_dir, relative_path, content="<xsd/>"):
        path = Path(root_dir) / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _file_entry(self, root_dir, relative_path, content="<xsd/>", role="root"):
        self._write_xsd_file(root_dir, relative_path, content)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return {
            "path": relative_path,
            "official_url": (
                "https://official.example.test/sifen/v150/"
                + Path(relative_path).name
            ),
            "sha256": digest,
            "role": role,
        }

    def _valid_manifest(self, root_schema="schemas/siRecepDE_v150.xsd"):
        return {
            "schema_family": "SIFEN",
            "country": "PY",
            "version": "150",
            "root_schema": root_schema,
            "source": {
                "base_url": "https://official.example.test/sifen/v150/",
                "downloaded_at": "2026-06-15",
            },
            "files": [],
            "dependency_map": {},
            "validation_policy": {
                "runtime_downloads_allowed": False,
            },
        }

    def _final_validation_schema(self):
        """Small test schema for structured-report mechanics only.

        This intentionally is not the official SIFEN v150 schema; official
        schema execution is covered separately with the vendored default
        assets.
        """
        return """<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="http://ekuatia.set.gov.py/sifen/xsd"
           xmlns="http://ekuatia.set.gov.py/sifen/xsd"
           elementFormDefault="qualified">
  <xs:element name="rDE">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="dVerFor">
          <xs:simpleType>
            <xs:restriction base="xs:string">
              <xs:pattern value="150"/>
            </xs:restriction>
          </xs:simpleType>
        </xs:element>
        <xs:element name="DE">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="dFecFirma" type="xs:dateTime"/>
            </xs:sequence>
            <xs:attribute name="Id" use="required" type="xs:string"/>
          </xs:complexType>
        </xs:element>
        <xs:any namespace="http://www.w3.org/2000/09/xmldsig#"
                processContents="skip"/>
        <xs:element name="gCamFuFD">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="dCarQR">
                <xs:simpleType>
                  <xs:restriction base="xs:string">
                    <xs:minLength value="1"/>
                  </xs:restriction>
                </xs:simpleType>
              </xs:element>
            </xs:sequence>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

    def _final_validation_service(self, root_dir):
        schema = self._final_validation_schema()
        manifest = self._valid_manifest()
        manifest["files"] = [
            self._file_entry(
                root_dir,
                "schemas/siRecepDE_v150.xsd",
                schema,
            ),
        ]
        manifest["dependency_map"] = {
            "schemas/siRecepDE_v150.xsd": [],
        }
        self._write_manifest(root_dir, manifest)
        return PyXsdValidationService(root_dir)

    def test_service_locates_expected_default_directory(self):
        service = PyXsdValidationService()

        self.assertEqual(
            service.get_xsd_root_dir(),
            Path(__file__).resolve().parents[1] / "xsd" / "sifen" / "v150",
        )

    def test_missing_manifest_is_handled_cleanly(self):
        with TemporaryDirectory() as root_dir:
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "missing manifest.json"):
                service.load_manifest()

    def test_malformed_manifest_is_handled_cleanly(self):
        with TemporaryDirectory() as root_dir:
            Path(root_dir, "manifest.json").write_text("{bad json", encoding="utf-8")
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "manifest is malformed"):
                service.load_manifest()

    def test_manifest_structure_is_validated(self):
        with TemporaryDirectory() as root_dir:
            self._write_manifest(root_dir, {"schema_family": "SIFEN"})
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "missing required keys"):
                service.validate_manifest()

    def test_root_schema_must_be_non_empty_string(self):
        with TemporaryDirectory() as root_dir:
            manifest = self._valid_manifest(root_schema=123)
            self._write_manifest(root_dir, manifest)
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "root_schema is required"):
                service.validate_manifest()

    def test_valid_manifest_shape_passes(self):
        with TemporaryDirectory() as root_dir:
            manifest = self._valid_manifest()
            manifest["files"] = [
                self._file_entry(root_dir, "schemas/siRecepDE_v150.xsd"),
            ]
            manifest["dependency_map"] = {
                "schemas/siRecepDE_v150.xsd": [],
            }
            self._write_manifest(root_dir, manifest)
            service = PyXsdValidationService(root_dir)

            self.assertEqual(service.validate_manifest()["version"], "150")

    def test_runtime_downloads_true_fails(self):
        with TemporaryDirectory() as root_dir:
            manifest = self._valid_manifest()
            manifest["validation_policy"]["runtime_downloads_allowed"] = True
            self._write_manifest(root_dir, manifest)
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "runtime_downloads_allowed to false"):
                service.validate_manifest()

    def test_file_entry_missing_required_keys_fails(self):
        required_keys = ("path", "official_url", "sha256", "role")
        for missing_key in required_keys:
            with self.subTest(missing_key=missing_key):
                with TemporaryDirectory() as root_dir:
                    entry = {
                        "path": "schemas/siRecepDE_v150.xsd",
                        "official_url": (
                            "https://official.example.test/sifen/v150/"
                            "siRecepDE_v150.xsd"
                        ),
                        "sha256": "abc123",
                        "role": "root",
                    }
                    del entry[missing_key]
                    manifest = self._valid_manifest()
                    manifest["files"] = [entry]
                    self._write_manifest(root_dir, manifest)
                    service = PyXsdValidationService(root_dir)

                    with self.assertRaisesRegex(ValidationError, "missing required keys"):
                        service.validate_manifest()

    def test_files_must_be_a_list(self):
        with TemporaryDirectory() as root_dir:
            manifest = self._valid_manifest()
            manifest["files"] = {}
            self._write_manifest(root_dir, manifest)
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "files must be a list"):
                service.validate_manifest()

    def test_manifest_path_cannot_escape_xsd_directory(self):
        with TemporaryDirectory() as root_dir:
            self._write_manifest(root_dir, self._valid_manifest("../outside.xsd"))
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "escapes the expected local XSD directory"):
                service.get_root_schema_path()

    def test_manifest_file_path_cannot_escape_xsd_directory(self):
        with TemporaryDirectory() as root_dir:
            manifest = self._valid_manifest()
            manifest["files"] = [
                {
                    "path": "../outside.xsd",
                    "official_url": (
                        "https://official.example.test/sifen/v150/outside.xsd"
                    ),
                    "sha256": "abc123",
                    "role": "root",
                }
            ]
            self._write_manifest(root_dir, manifest)
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "escapes the expected local XSD directory"):
                service.validate_manifest()

    def test_dependency_map_path_cannot_escape_xsd_directory(self):
        with TemporaryDirectory() as root_dir:
            manifest = self._valid_manifest()
            manifest["dependency_map"] = {
                "schemas/siRecepDE_v150.xsd": ["../outside.xsd"],
            }
            self._write_manifest(root_dir, manifest)
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "escapes the expected local XSD directory"):
                service.validate_manifest()

    def test_dependency_map_entries_must_be_lists(self):
        with TemporaryDirectory() as root_dir:
            manifest = self._valid_manifest()
            manifest["dependency_map"] = {
                "schemas/siRecepDE_v150.xsd": "schemas/types.xsd",
            }
            self._write_manifest(root_dir, manifest)
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "must be a list"):
                service.validate_manifest()

    def test_checksum_validation_passes_for_listed_file(self):
        with TemporaryDirectory() as root_dir:
            manifest = self._valid_manifest()
            manifest["files"] = [
                self._file_entry(root_dir, "schemas/siRecepDE_v150.xsd", "<schema/>"),
            ]
            self._write_manifest(root_dir, manifest)
            service = PyXsdValidationService(root_dir)

            self.assertTrue(service.validate_checksums())

    def test_checksum_validation_fails_for_missing_file(self):
        with TemporaryDirectory() as root_dir:
            manifest = self._valid_manifest()
            manifest["files"] = [
                {
                    "path": "schemas/missing.xsd",
                    "official_url": (
                        "https://official.example.test/sifen/v150/missing.xsd"
                    ),
                    "sha256": "abc123",
                    "role": "root",
                }
            ]
            self._write_manifest(root_dir, manifest)
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "listed file is missing"):
                service.validate_checksums()

    def test_checksum_validation_fails_for_mismatch(self):
        with TemporaryDirectory() as root_dir:
            self._write_xsd_file(root_dir, "schemas/siRecepDE_v150.xsd", "<schema/>")
            manifest = self._valid_manifest()
            manifest["files"] = [
                {
                    "path": "schemas/siRecepDE_v150.xsd",
                    "official_url": (
                        "https://official.example.test/sifen/v150/"
                        "siRecepDE_v150.xsd"
                    ),
                    "sha256": "0" * 64,
                    "role": "root",
                }
            ]
            self._write_manifest(root_dir, manifest)
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "checksum mismatch"):
                service.validate_checksums()

    def test_local_resolver_blocks_http_imports(self):
        with TemporaryDirectory() as root_dir:
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "external reference blocked"):
                service.resolve_schema_reference("https://example.test/schema.xsd")

    def test_local_resolver_blocks_outside_root_paths(self):
        with TemporaryDirectory() as root_dir:
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "escapes the expected local XSD directory"):
                service.resolve_schema_reference("../outside.xsd")

    def test_missing_root_schema_is_handled_cleanly(self):
        with TemporaryDirectory() as root_dir:
            self._write_manifest(root_dir, self._valid_manifest())
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "root schema is missing"):
                service.get_root_schema_path()

    def test_compile_schema_fails_with_useful_message_when_assets_absent(self):
        with TemporaryDirectory() as root_dir:
            self._write_manifest(root_dir, self._valid_manifest())
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "root schema is missing"):
                service.compile_schema()

    def test_validate_xml_fails_cleanly_when_schema_unavailable(self):
        with TemporaryDirectory() as root_dir:
            self._write_manifest(root_dir, self._valid_manifest())
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "root schema is missing"):
                service.validate_xml("<root/>")

    def test_vendored_manifest_and_dependency_tree_are_valid(self):
        service = PyXsdValidationService()

        manifest = service.validate_manifest()

        self.assertEqual(manifest["root_schema"], "schemas/siRecepDE_v150.xsd")
        self.assertEqual(len(manifest["files"]), 8)
        self.assertEqual(
            manifest["dependency_map"]["schemas/siRecepDE_v150.xsd"],
            ["schemas/DE_v150.xsd"],
        )
        self.assertEqual(
            manifest["dependency_map"]["schemas/DE_v150.xsd"],
            [
                "schemas/xmldsig-core-schema.xsd",
                "schemas/Paises_v100.xsd",
                "schemas/Departamentos_v141.xsd",
                "schemas/Monedas_v150.xsd",
                "schemas/Unidades_Medida_v141.xsd",
                "schemas/DE_Types_v150.xsd",
            ],
        )
        for leaf_path in manifest["dependency_map"]["schemas/DE_v150.xsd"]:
            self.assertEqual(manifest["dependency_map"][leaf_path], [])

    def test_vendored_files_exist_and_checksums_match(self):
        service = PyXsdValidationService()

        self.assertTrue(service.validate_checksums())

    def test_official_schema_url_resolves_to_vendored_file(self):
        service = PyXsdValidationService()

        path = service.resolve_schema_reference(
            "https://ekuatia.set.gov.py/sifen/xsd/DE_v150.xsd"
        )

        self.assertEqual(
            path,
            service.get_xsd_root_dir() / "schemas" / "DE_v150.xsd",
        )

    def test_unlisted_external_schema_url_remains_blocked(self):
        service = PyXsdValidationService()

        with self.assertRaisesRegex(ValidationError, "external reference blocked"):
            service.resolve_schema_reference(
                "https://example.test/untrusted-schema.xsd"
            )

    def test_vendored_root_schema_compiles_without_runtime_downloads(self):
        service = PyXsdValidationService()

        schema = service.compile_schema()

        self.assertIsNotNone(schema)

    def test_full_validation_still_requires_signature_and_qr_stages(self):
        manifest = PyXsdValidationService().validate_manifest()

        self.assertEqual(
            manifest["full_xsd_validation_requires"],
            ["dFecFirma", "ds:Signature", "gCamFuFD/dCarQR"],
        )

    def test_final_signed_xml_validation_uses_vendored_schema_policy(self):
        service = PyXsdValidationService()

        manifest = service.validate_manifest()

        self.assertEqual(manifest["version"], "150")
        self.assertFalse(manifest["validation_policy"]["runtime_downloads_allowed"])
        self.assertTrue(str(service.get_root_schema_path()).endswith("siRecepDE_v150.xsd"))

    def test_structured_report_mechanics_valid_complete_xml_passes_with_simplified_schema(self):
        with TemporaryDirectory() as root_dir:
            service = self._final_validation_service(root_dir)

            report = service.validate_final_signed_xml(self.COMPLETE_XML)

            self.assertTrue(report["valid"])
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["warnings"], [])
            self.assertTrue(report["schema_used"].endswith("schemas/siRecepDE_v150.xsd"))

    def test_structured_report_mechanics_missing_signature_fails(self):
        xml = self.COMPLETE_XML.replace(
            b"""  <ds:Signature>
    <ds:SignedInfo>
      <ds:Reference URI="#01234567890123456789012345678901234567890123">
        <ds:DigestValue>digest-fixture</ds:DigestValue>
      </ds:Reference>
    </ds:SignedInfo>
  </ds:Signature>
""",
            b"",
        )
        with TemporaryDirectory() as root_dir:
            service = self._final_validation_service(root_dir)

            report = service.validate_final_signed_xml(xml)

            self.assertFalse(report["valid"])
            self.assertIn(
                "Final signed Paraguay XML must contain exactly one XMLDSig Signature.",
                [error["message"] for error in report["errors"]],
            )

    def test_structured_report_mechanics_missing_qr_fails(self):
        xml = self.COMPLETE_XML.replace(
            b"""  <gCamFuFD>
    <dCarQR>https://example.test/qr?nVersion=150&amp;Id=01234567890123456789012345678901234567890123&amp;cHashQR=abc</dCarQR>
  </gCamFuFD>
""",
            b"",
        )
        with TemporaryDirectory() as root_dir:
            service = self._final_validation_service(root_dir)

            report = service.validate_final_signed_xml(xml)

            self.assertFalse(report["valid"])
            self.assertIn(
                "Final signed Paraguay XML must contain gCamFuFD/dCarQR QR content.",
                [error["message"] for error in report["errors"]],
            )

    def test_structured_report_mechanics_malformed_xml_fails(self):
        with TemporaryDirectory() as root_dir:
            service = self._final_validation_service(root_dir)

            report = service.validate_final_signed_xml(b"<rDE>")

            self.assertFalse(report["valid"])
            self.assertTrue(report["errors"])
            self.assertIn("Premature end of data", report["errors"][0]["message"])

    def test_structured_report_mechanics_schema_violation_fails(self):
        xml = self.COMPLETE_XML.replace(b"<dVerFor>150</dVerFor>", b"<dVerFor>999</dVerFor>")
        with TemporaryDirectory() as root_dir:
            service = self._final_validation_service(root_dir)

            report = service.validate_final_signed_xml(xml)

            self.assertFalse(report["valid"])
            self.assertTrue(report["errors"])
            self.assertIn("dVerFor", [error["failing_element"] for error in report["errors"]])

    def test_structured_report_mechanics_results_are_deterministic(self):
        xml = self.COMPLETE_XML.replace(b"<dVerFor>150</dVerFor>", b"<dVerFor>999</dVerFor>")
        with TemporaryDirectory() as root_dir:
            service = self._final_validation_service(root_dir)

            first = service.validate_final_signed_xml(xml)
            second = service.validate_final_signed_xml(xml)

            self.assertEqual(first, second)

    def test_official_vendored_schema_execution_returns_structured_errors(self):
        service = PyXsdValidationService()

        report = service.validate_final_signed_xml(self.COMPLETE_XML)

        self.assertFalse(report["valid"])
        self.assertTrue(report["schema_used"].endswith("schemas/siRecepDE_v150.xsd"))
        self.assertTrue(report["errors"])
        self.assertTrue(all(set(error) == {"failing_element", "line", "column", "message"} for error in report["errors"]))
        self.assertTrue(any(error["message"] for error in report["errors"]))
