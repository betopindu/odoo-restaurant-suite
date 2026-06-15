import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

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
    REQUIRED_FILE_KEYS = {"path", "sha256", "role"}

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
        if not isinstance(manifest.get("root_schema"), str) or not manifest.get("root_schema"):
            raise ValidationError("SIFEN XSD manifest root_schema is required.")
        self._resolve_local_path(manifest["root_schema"])
        self._validate_runtime_policy(manifest)
        self._validate_manifest_files(manifest)
        self._validate_dependency_map(manifest)
        return manifest

    def validate_checksums(self):
        manifest = self.validate_manifest()
        for item in manifest["files"]:
            file_path = self._resolve_local_path(item["path"])
            if not file_path.exists():
                raise ValidationError(f"SIFEN XSD listed file is missing: {file_path}.")
            digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if digest.lower() != item["sha256"].lower():
                raise ValidationError(
                    "SIFEN XSD checksum mismatch for "
                    f"{item['path']}: expected {item['sha256']}, got {digest}."
                )
        return True

    def resolve_schema_reference(self, schema_location):
        if self._is_external_reference(schema_location):
            raise ValidationError(
                "SIFEN XSD imports/includes must be local; external reference blocked: "
                f"{schema_location}."
            )
        path = self._resolve_local_path(schema_location)
        if not path.exists():
            raise ValidationError(f"SIFEN XSD import/include is missing: {path}.")
        return path

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
        self.validate_checksums()
        root_schema = self.get_root_schema_path()
        try:
            parser = self._schema_parser()
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
        if self._is_external_reference(relative_path):
            raise ValidationError(
                "SIFEN XSD path must be local; external references are not allowed: "
                f"{relative_path}."
            )
        xsd_root = self.get_xsd_root_dir()
        candidate = (xsd_root / relative_path).resolve()
        if not self._is_relative_to(candidate, xsd_root.resolve()):
            raise ValidationError(
                "SIFEN XSD manifest path escapes the expected local XSD directory: "
                f"{relative_path}."
            )
        return candidate

    def _validate_runtime_policy(self, manifest):
        policy = manifest.get("validation_policy")
        if not isinstance(policy, dict):
            raise ValidationError("SIFEN XSD manifest validation_policy must be an object.")
        if policy.get("runtime_downloads_allowed") is not False:
            raise ValidationError(
                "SIFEN XSD manifest must set validation_policy.runtime_downloads_allowed to false."
            )

    def _validate_manifest_files(self, manifest):
        files = manifest.get("files")
        if not isinstance(files, list):
            raise ValidationError("SIFEN XSD manifest files must be a list.")
        for index, item in enumerate(files, start=1):
            if not isinstance(item, dict):
                raise ValidationError(f"SIFEN XSD manifest file entry {index} must be an object.")
            missing = sorted(self.REQUIRED_FILE_KEYS - set(item))
            if missing:
                raise ValidationError(
                    f"SIFEN XSD manifest file entry {index} is missing required keys: "
                    + ", ".join(missing)
                    + "."
                )
            for key in self.REQUIRED_FILE_KEYS:
                if not isinstance(item.get(key), str) or not item.get(key):
                    raise ValidationError(
                        f"SIFEN XSD manifest file entry {index} key {key} is required."
                    )
            self._resolve_local_path(item["path"])

    def _validate_dependency_map(self, manifest):
        dependency_map = manifest.get("dependency_map")
        if not isinstance(dependency_map, dict):
            raise ValidationError("SIFEN XSD manifest dependency_map must be an object.")
        for source, dependencies in dependency_map.items():
            if not isinstance(source, str) or not source:
                raise ValidationError("SIFEN XSD dependency map source path is required.")
            self._resolve_local_path(source)
            if not isinstance(dependencies, list):
                raise ValidationError(
                    f"SIFEN XSD dependency map entry for {source} must be a list."
                )
            for dependency in dependencies:
                if not isinstance(dependency, str) or not dependency:
                    raise ValidationError(
                        f"SIFEN XSD dependency map entry for {source} contains an invalid path."
                    )
                self._resolve_local_path(dependency)

    def _schema_parser(self):
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
        parser.resolvers.add(_LocalXsdResolver(self))
        return parser

    def _is_external_reference(self, value):
        parsed = urlparse(str(value))
        return bool(parsed.scheme or parsed.netloc)

    def _is_relative_to(self, path, parent):
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False


class _LocalXsdResolver(etree.Resolver):
    def __init__(self, service):
        super().__init__()
        self.service = service

    def resolve(self, url, pubid, context):
        path = self.service.resolve_schema_reference(url)
        return self.resolve_filename(str(path), context)
