"""Contract tests for strict, source-preserving CSV event ingestion."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from catalyst.adapters.csv_event_feed import CSV_HEADER, CsvEventFeed
from catalyst.domain.enums import EventImportance, EventStatus

ROOT = Path(__file__).resolve().parents[2]
INGESTED_AT = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def valid_row(event_id: str = "TEST_EVENT_001") -> list[str]:
    return [
        event_id,
        "Test release",
        "2030-01-10T13:30:00+00:00",
        "USD",
        "HIGH",
        "SCHEDULED",
        "US100|US500",
        "manual_csv",
        "",
        "2.5",
        "2.4",
    ]


class CsvEventFeedTests(TestCase):
    def load_rows(self, rows: list[list[str]]) -> CsvEventFeed:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.csv"
            content = "\n".join(",".join(row) for row in [list(CSV_HEADER), *rows]) + "\n"
            path.write_text(content, encoding="utf-8")
            return CsvEventFeed.load(path, ingested_at=INGESTED_AT)

    def test_checked_in_example_loads_and_preserves_source_fields(self) -> None:
        feed = CsvEventFeed.load(
            ROOT / "config" / "events.example.csv",
            ingested_at=INGESTED_AT,
        )

        self.assertEqual(len(feed.records), 3)
        record = feed.records[0]
        self.assertEqual(record.event.event_id, "SYNTH_US_CPI_001")
        self.assertEqual(record.event.importance, EventImportance.HIGH)
        self.assertEqual(record.event.status, EventStatus.SCHEDULED)
        self.assertEqual(record.event.eligible_symbols[:2], ("US100", "US500"))
        self.assertEqual(record.source_row_number, 2)
        self.assertEqual(tuple(record.raw_mapping()), CSV_HEADER)
        self.assertEqual(record.raw_mapping()["consensus"], "")
        self.assertEqual(len(record.raw_hash), 64)
        self.assertEqual(len(record.normalized_hash), 64)

    def test_range_is_inclusive_and_results_are_stably_ordered(self) -> None:
        later = valid_row("LATER")
        earlier = valid_row("EARLIER")
        earlier[2] = "2030-01-09T13:30:00Z"
        feed = self.load_rows([later, earlier])

        events = feed.events_between(
            datetime(2030, 1, 9, 13, 30, tzinfo=UTC),
            datetime(2030, 1, 10, 13, 30, tzinfo=UTC),
        )

        self.assertEqual(tuple(event.event_id for event in events), ("EARLIER", "LATER"))

    def test_duplicate_event_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate event_id"):
            self.load_rows([valid_row(), valid_row()])

    def test_naive_and_non_utc_timestamps_are_rejected(self) -> None:
        for timestamp in ("2030-01-10T13:30:00", "2030-01-10T14:30:00+01:00"):
            row = valid_row()
            row[2] = timestamp
            with self.subTest(timestamp=timestamp), self.assertRaisesRegex(ValueError, "UTC"):
                self.load_rows([row])

    def test_bad_importance_status_and_missing_identifier_are_rejected(self) -> None:
        cases = ((4, "CRITICAL", "importance"), (5, "PENDING", "status"), (0, "", "event_id"))
        for index, value, message in cases:
            row = valid_row()
            row[index] = value
            with self.subTest(field=message), self.assertRaisesRegex(ValueError, message):
                self.load_rows([row])

    def test_optional_numbers_are_strict_finite_decimal_strings(self) -> None:
        for value in ("NaN", "Infinity", "not-a-number", " 2.5"):
            row = valid_row()
            row[9] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "consensus"):
                self.load_rows([row])

    def test_symbol_inference_and_unknown_columns_are_not_allowed(self) -> None:
        row = valid_row()
        row[6] = "US100|us500"
        with self.assertRaisesRegex(ValueError, "uppercase logical symbols"):
            self.load_rows([row])

        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.csv"
            path.write_text("unexpected,header\nvalue,value\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "header"):
                CsvEventFeed.load(path, ingested_at=INGESTED_AT)

    def test_ingestion_time_must_be_explicit_utc(self) -> None:
        path = ROOT / "config" / "events.example.csv"
        with self.assertRaisesRegex(ValueError, "ingested_at.*UTC"):
            CsvEventFeed.load(path, ingested_at=datetime(2026, 8, 28, 12, 0))

    def test_empty_invalid_utf8_and_wrong_field_count_are_rejected(self) -> None:
        cases = (
            (b"", "empty"),
            (b"\xff\xfe", "UTF-8"),
            ((",".join(CSV_HEADER) + "\nonly,three,fields\n").encode(), "field count"),
        )
        for content, message in cases:
            with TemporaryDirectory() as directory:
                path = Path(directory) / "events.csv"
                path.write_bytes(content)
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    CsvEventFeed.load(path, ingested_at=INGESTED_AT)

    def test_strict_identifiers_source_symbols_and_timestamp_are_rejected(self) -> None:
        cases = (
            (0, "bad id", "event_id"),
            (1, " Test release", "whitespace"),
            (1, "Test\x00release", "null byte"),
            (2, "not-a-time", "ISO-8601"),
            (3, "usd", "currency"),
            (6, "US100|US100", "duplicates"),
            (7, "provider", "manual_csv"),
        )
        for index, value, message in cases:
            row = valid_row()
            row[index] = value
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.load_rows([row])

    def test_constructor_rejects_empty_and_duplicate_records(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            CsvEventFeed(())
        record = self.load_rows([valid_row()]).records[0]
        with self.assertRaisesRegex(ValueError, "must be unique"):
            CsvEventFeed((record, record))

    def test_invalid_query_range_and_non_utc_boundary_are_rejected(self) -> None:
        feed = self.load_rows([valid_row()])
        start = datetime(2030, 1, 10, 13, 30, tzinfo=UTC)
        with self.assertRaisesRegex(ValueError, "must not precede"):
            feed.records_between(start, start - timedelta(seconds=1))
        with self.assertRaisesRegex(ValueError, "start.*UTC"):
            feed.events_between(datetime(2030, 1, 10, 13, 30), start)
