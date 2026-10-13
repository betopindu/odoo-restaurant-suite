import hashlib
from pathlib import Path
from urllib.parse import urlparse

from lxml import etree
from odoo.exceptions import ValidationError


class _EventSchemaResolver(etree.Resolver):
    def __init__(self, event_dir, shared_dir):
        super().__init__()
        self.event_dir = Path(event_dir)
        self.shared_dir = Path(shared_dir)

    def resolve(self, url, _public_id, context):
        name = Path(urlparse(url).path).name
        candidate = self.event_dir / name
        if not candidate.exists():
            candidate = self.shared_dir / name
        if not candidate.exists():
            raise OSError(f"Unvendored SIFEN event schema dependency: {name}")
        return self.resolve_filename(str(candidate), context)


class PySifenEventXsdValidationService:
    """Validate signed SIFEN events against pinned official v150 schemas."""

    SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
    FILE_HASHES = {
        "siRecepEvento_v150.xsd": "27cb5b1438894427c92c276c18883c6df3472de3a4ce78caf9fb7f1838d54473",
        "Evento_v150.xsd": "30321c18269bbf126bf54637738ad62d8e65887311027ae4c7d6026482983cfe",
        "Evento_Types_v150.xsd": "0402d380cdea0b80205af95902c4b1a3f9117778c067161e86b48ced3e09dc04",
    }

    def __init__(self, event_dir=None, shared_dir=None):
        addon = Path(__file__).resolve().parents[1]
        self.event_dir = Path(event_dir or addon / "xsd/sifen/events/v150")
        self.shared_dir = Path(shared_dir or addon / "xsd/sifen/v150/schemas")

    def validate_signed_event(self, signed_event_xml):
        schema = self._compile()
        try:
            event = etree.fromstring(
                signed_event_xml,
                parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True),
            )
        except etree.XMLSyntaxError as error:
            raise ValidationError("Signed SIFEN event XML is malformed.") from error
        group = etree.Element(f"{{{self.SIFEN_NS}}}gGroupGesEve", nsmap={None: self.SIFEN_NS})
        group.append(event)
        if not schema.validate(group):
            error = schema.error_log.last_error
            element = self._element(error.message if error is not None else "")
            location = f" at {element}" if element else ""
            raise ValidationError(
                f"Signed SIFEN event failed official v150 XSD validation{location}."
            )
        return True

    def _compile(self):
        self._validate_assets()
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
        parser.resolvers.add(_EventSchemaResolver(self.event_dir, self.shared_dir))
        try:
            return etree.XMLSchema(
                etree.parse(str(self.event_dir / "siRecepEvento_v150.xsd"), parser)
            )
        except (etree.XMLSyntaxError, etree.XMLSchemaParseError, OSError) as error:
            raise ValidationError("Official SIFEN event XSD assets could not be compiled.") from error

    def _validate_assets(self):
        for name, expected in self.FILE_HASHES.items():
            path = self.event_dir / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValidationError(f"Official SIFEN event XSD asset is missing or invalid: {name}.")

    @staticmethod
    def _element(message):
        marker = "Element '{http://ekuatia.set.gov.py/sifen/xsd}"
        if marker not in message:
            return ""
        return message.split(marker, 1)[1].split("'", 1)[0]
