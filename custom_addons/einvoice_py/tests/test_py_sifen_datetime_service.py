from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from odoo.exceptions import ValidationError
from odoo.tests.common import BaseCase

from odoo.addons.einvoice_py.services.py_sifen_datetime_service import (
    PySifenDatetimeService,
)


class TestPySifenDatetimeService(BaseCase):
    def test_naive_odoo_datetime_is_interpreted_as_utc(self):
        self.assertEqual(
            PySifenDatetimeService.format_fiscal_datetime(
                datetime(2026, 8, 5, 23, 12, 39)
            ),
            "2026-08-05T20:12:39",
        )

    def test_utc_and_ireland_instants_serialize_identically(self):
        utc_value = datetime(2026, 8, 5, 23, 12, 39, tzinfo=timezone.utc)
        ireland_value = datetime(
            2026,
            8,
            6,
            0,
            12,
            39,
            tzinfo=ZoneInfo("Europe/Dublin"),
        )

        self.assertEqual(
            PySifenDatetimeService.format_fiscal_datetime(utc_value),
            "2026-08-05T20:12:39",
        )
        self.assertEqual(
            PySifenDatetimeService.format_fiscal_datetime(ireland_value),
            "2026-08-05T20:12:39",
        )

    def test_iana_rules_cover_paraguay_daylight_saving_history(self):
        self.assertEqual(
            PySifenDatetimeService.format_fiscal_datetime(
                datetime(2024, 1, 15, 12, 0, 0)
            ),
            "2024-01-15T09:00:00",
        )
        self.assertEqual(
            PySifenDatetimeService.format_fiscal_datetime(
                datetime(2024, 7, 15, 12, 0, 0)
            ),
            "2024-07-15T08:00:00",
        )

    def test_existing_sifen_local_serialization_is_stable(self):
        self.assertEqual(
            PySifenDatetimeService.format_fiscal_datetime(
                "2026-08-05T20:12:39"
            ),
            "2026-08-05T20:12:39",
        )

    def test_signing_time_has_explicit_strict_before_margin(self):
        self.assertEqual(
            PySifenDatetimeService.format_signing_datetime(
                datetime(2026, 8, 5, 23, 51, 1)
            ),
            "2026-08-05T20:50:01",
        )

    def test_signing_margin_is_host_timezone_independent(self):
        utc_value = datetime(2026, 8, 5, 23, 51, 1, tzinfo=timezone.utc)
        ireland_value = datetime(
            2026, 8, 6, 0, 51, 1, tzinfo=ZoneInfo("Europe/Dublin")
        )

        self.assertEqual(
            PySifenDatetimeService.format_signing_datetime(utc_value),
            PySifenDatetimeService.format_signing_datetime(ireland_value),
        )

    def test_existing_retry_signing_time_does_not_apply_margin_twice(self):
        self.assertEqual(
            PySifenDatetimeService.format_signing_datetime(
                "2026-08-05T20:50:01"
            ),
            "2026-08-05T20:50:01",
        )

    def test_invalid_value_is_rejected_safely(self):
        with self.assertRaisesRegex(ValidationError, "timestamp is invalid"):
            PySifenDatetimeService.format_fiscal_datetime("not-a-time")
