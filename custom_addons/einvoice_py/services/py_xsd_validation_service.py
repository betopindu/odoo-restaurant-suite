import json
from pathlib import Path

from lxml import etree

from odoo.exceptions import ValidationError


class PyXsdValidationService:
    """Load future locally pinned SIFEN XSD assets.

    This service is infrastructure only. Until official XSD assets are pinned
    under the expected directory, schema compilation and XML validation fail
    explicitly instead of silently passing.
    """

    REQUIRED_MANIFEST_KEYS = {
        "schema_family",
        "country",
        "version",
        "root_schema",
        "source",
        "files",
        "dependency_map",
        "validation_policy",
    }

    def __init__(self, xsd_root_dir=None):
        self._xsd_root_dir = Path(xsd_root_dir).resolve() if xsd_root_dir else None

    def get_xsd_root_dir(self):
        if self._xsd_root_dir:
            return self._xsd_root_dir
        addon_root = Path(__file__).resolve().parents[1]
        return addon_root / "xsd" / "sifen" / "v150"

    def load_manifest(self):
        manifest_path = self.get_xsd_root_dir() / "manifest.json"
        if not manifest_path.exists():
            raise ValidationError(
                "SIFEN XSD assets are not installed; missing manifest.json at "
                f"{manifest_path}."
            )
        try:
            with manifest_path.open("r", encoding="utf-8") as manifest_file:
                return json.load(manifest_file)
        except json.JSONDecodeError as error:
            raise ValidationError(f"SIFEN XSD manifest is malformed: {error}") from error

    def validate_manifest(self):
        manifest = self.load_manifest()
        missing = sorted(self.REQUIRED_MANIFEST_KEYS - set(manifest))
        if missing:
            raise ValidationError(
                "SIFEN XSD manifest is missing required keys: "
                + ", ".join(missing)
                + "."
            )
        if manifest.get("schema_family") != "SIFEN":
            raise ValidationError("SIFEN XSD manifest schema_family must be SIFEN.")
        if manifest.get("country") != "PY":
            raise ValidationError("SIFEN XSD manifest country must be PY.")
        if not manifest.get("root_schema"):
            raise ValidationError("SIFEN XSD manifest root_schema is required.")
        return manifest

    def get_root_schema_path(self):
        manifest = self.validate_manifest()
        root_schema = self._resolve_local_path(manifest["root_schema"])
        if not root_schema.exists():
            raise ValidationError(
                "SIFEN XSD root schema is missing: "
                f"{root_schema}."
            )
        return root_schema

    def compile_schema(self):
        root_schema = self.get_root_schema_path()
        try:
            parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
            schema_doc = etree.parse(str(root_schema), parser)
            return etree.XMLSchema(schema_doc)
        except (etree.XMLSyntaxError, etree.XMLSchemaParseError, OSError) as error:
            raise ValidationError(f"SIFEN XSD schema could not be compiled: {error}") from error

    def validate_xml(self, xml_content):
        schema = self.compile_schema()
        try:
            parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
            if isinstance(xml_content, str):
                xml_content = xml_content.encode("utf-8")
            xml_doc = etree.fromstring(xml_content, parser)
        except etree.XMLSyntaxError as error:
            raise ValidationError(f"XML content is malformed: {error}") from error
        if not schema.validate(xml_doc):
            error = schema.error_log.last_error
            detail = f": {error.message}" if error is not None else ""
            raise ValidationError(f"XML content does not validate against SIFEN XSD{detail}.")
        return True

    def _resolve_local_path(self, relative_path):
        xsd_root = self.get_xsd_root_dir()
        candidate = (xsd_root / relative_path).resolve()
        if not self._is_relative_to(candidate, xsd_root.resolve()):
            raise ValidationError(
                "SIFEN XSD manifest path escapes the expected local XSD directory: "
                f"{relative_path}."
            )
        return candidate

    def _is_relative_to(self, path, parent):
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False
