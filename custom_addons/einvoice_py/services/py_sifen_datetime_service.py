from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from odoo import fields
from odoo.exceptions import ValidationError


class PySifenDatetimeService:
    """Serialize UTC instants as Paraguay civil time for SIFEN fields."""

    PARAGUAY_TIMEZONE = ZoneInfo("America/Asuncion")
    SIFEN_FORMAT = "%Y-%m-%dT%H:%M:%S"

    @classmethod
    def format_fiscal_datetime(cls, value, *, field_label="Paraguay fiscal timestamp"):
        if isinstance(value, str) and cls._is_serialized_fiscal_time(value):
            return value

        instant = cls._instant(value, field_label=field_label)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        return instant.astimezone(cls.PARAGUAY_TIMEZONE).strftime(
            cls.SIFEN_FORMAT
        )

    @classmethod
    def _instant(cls, value, *, field_label):
        if isinstance(value, datetime):
            return value
        try:
            instant = fields.Datetime.to_datetime(value)
        except (TypeError, ValueError):
            instant = None
        if instant is None:
            raise ValidationError(f"{field_label} is invalid.") from None
        return instant

    @classmethod
    def _is_serialized_fiscal_time(cls, value):
        try:
            return datetime.strptime(value, cls.SIFEN_FORMAT).strftime(
                cls.SIFEN_FORMAT
            ) == value
        except (TypeError, ValueError):
            return False
