import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.einvoice_py.services.py_xsd_validation_service import PyXsdValidationService


class TestPyXsdValidationService(TransactionCase):
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
                "url": "https://official.example.test/sifen/v150",
                "downloaded_at": "2026-06-15",
            },
            "files": [],
            "dependency_map": {},
            "validation_policy": {
                "runtime_downloads_allowed": False,
            },
        }

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
        required_keys = ("path", "sha256", "role")
        for missing_key in required_keys:
            with self.subTest(missing_key=missing_key):
                with TemporaryDirectory() as root_dir:
                    entry = {
                        "path": "schemas/siRecepDE_v150.xsd",
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
