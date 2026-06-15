import json
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

    def test_manifest_path_cannot_escape_xsd_directory(self):
        with TemporaryDirectory() as root_dir:
            self._write_manifest(root_dir, self._valid_manifest("../outside.xsd"))
            service = PyXsdValidationService(root_dir)

            with self.assertRaisesRegex(ValidationError, "escapes the expected local XSD directory"):
                service.get_root_schema_path()

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
