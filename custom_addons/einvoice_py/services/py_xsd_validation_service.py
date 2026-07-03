import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

from lxml import etree

from odoo.exceptions import ValidationError


class PyXsdValidationService:
    """Load and validate the locally pinned SIFEN XSD assets."""

    SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
    XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"

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
    REQUIRED_FILE_KEYS = {"path", "official_url", "sha256", "role"}

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
        parsed = urlparse(str(schema_location))
        if parsed.scheme in {"http", "https"}:
            local_path = self._get_official_url_map().get(str(schema_location))
            if not local_path:
                raise ValidationError(
                    "SIFEN XSD imports/includes must be local; external reference blocked: "
                    f"{schema_location}."
                )
            return self._require_existing_schema_path(local_path)
        if parsed.scheme == "file":
            return self._require_existing_schema_path(Path(unquote(parsed.path)))
        if parsed.scheme or parsed.netloc:
            raise ValidationError(
                "SIFEN XSD imports/includes must be local; external reference blocked: "
                f"{schema_location}."
            )
        path = self._resolve_local_path(schema_location)
        if path.exists():
            return path
        schema_path = self._resolve_local_path(
            Path("schemas") / Path(str(schema_location)).name
        )
        return self._require_existing_schema_path(schema_path)

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

    def validate_final_signed_xml(self, xml_content):
        """Validate final signed Paraguay XML with QR content.

        Returns a structured, secret-free report instead of raising for normal
        XML/schema validation failures. Manifest/schema installation errors
        still raise because they indicate local runtime misconfiguration.
        """
        schema = self.compile_schema()
        report = self._empty_report()
        try:
            xml_doc = self._parse_xml(xml_content)
        except etree.XMLSyntaxError as error:
            report["errors"].append(self._error_entry(error=error))
            return report

        self._validate_final_stage_structure(xml_doc, report)
        if schema.validate(xml_doc):
            report["valid"] = not report["errors"]
            return report

        for error in schema.error_log:
            report["errors"].append(self._error_entry(error=error))
        report["valid"] = False
        return report

    def _empty_report(self):
        return {
            "valid": False,
            "errors": [],
            "warnings": [],
            "schema_used": str(self.get_root_schema_path()),
        }

    def _parse_xml(self, xml_content):
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
        if isinstance(xml_content, str):
            xml_content = xml_content.encode("utf-8")
        return etree.fromstring(xml_content, parser)

    def _validate_final_stage_structure(self, xml_doc, report):
        signature_nodes = xml_doc.findall(f".//{{{self.XMLDSIG_NS}}}Signature")
        if len(signature_nodes) != 1:
            report["errors"].append(self._manual_error(
                "Final signed Paraguay XML must contain exactly one XMLDSig Signature.",
                failing_element="Signature",
            ))
        qr_nodes = xml_doc.findall(f"{{{self.SIFEN_NS}}}gCamFuFD/{{{self.SIFEN_NS}}}dCarQR")
        if len(qr_nodes) != 1 or not (qr_nodes[0].text or "").strip():
            report["errors"].append(self._manual_error(
                "Final signed Paraguay XML must contain gCamFuFD/dCarQR QR content.",
                failing_element="dCarQR",
            ))

    def _manual_error(self, message, failing_element=None, line=None, column=None):
        return {
            "failing_element": failing_element,
            "line": line,
            "column": column,
            "message": message,
        }

    def _error_entry(self, error):
        failing_element = self._failing_element_from_message(getattr(error, "message", ""))
        return {
            "failing_element": failing_element,
            "line": getattr(error, "line", None),
            "column": getattr(error, "column", None),
            "message": getattr(error, "message", str(error)),
        }

    def _failing_element_from_message(self, message):
        if not message:
            return None
        start = message.find("Element '")
        if start != -1:
            start += len("Element '")
            end = message.find("'", start)
            if end != -1:
                value = message[start:end]
                return value.rsplit("}", 1)[-1]
        return None

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
        source = manifest.get("source")
        if not isinstance(source, dict) or not isinstance(source.get("base_url"), str):
            raise ValidationError("SIFEN XSD manifest source.base_url is required.")
        source_base_url = source["base_url"]
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
            if not item["official_url"].startswith(source_base_url):
                raise ValidationError(
                    f"SIFEN XSD manifest file entry {index} official_url must use "
                    "the official source base URL."
                )

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

    def _get_official_url_map(self):
        manifest_path = self.get_xsd_root_dir() / "manifest.json"
        if not manifest_path.exists():
            return {}
        manifest = self.load_manifest()
        return {
            item["official_url"]: self._resolve_local_path(item["path"])
            for item in manifest.get("files", [])
            if isinstance(item, dict)
            and isinstance(item.get("official_url"), str)
            and isinstance(item.get("path"), str)
        }

    def _require_existing_schema_path(self, path):
        path = Path(path).resolve()
        xsd_root = self.get_xsd_root_dir().resolve()
        if not self._is_relative_to(path, xsd_root):
            raise ValidationError(
                "SIFEN XSD import/include escapes the expected local XSD directory: "
                f"{path}."
            )
        if not path.exists():
            raise ValidationError(f"SIFEN XSD import/include is missing: {path}.")
        return path

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
