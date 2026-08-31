"""Validation tests for Phase 3 persistence and reconciliation records."""

from dataclasses import replace
from datetime import datetime
from typing import Any, cast
from unittest import TestCase

from catalyst.engine.durable_execution import DurableSubmissionResult
from catalyst.engine.reconciliation import RestartReconciliationReport
from catalyst.ports.event_feed import SourceEventRecord
from catalyst.ports.journal import (
    JournalEntryKind,
    JournalEntryRecord,
    OrderIntentRecord,
    OrderIntentState,
)
from catalyst.ports.reconciliation import BrokerOrderLookup, BrokerOrderState
from tests.fixtures import READY_TIME, event

HASH = "a" * 64


def source_record() -> SourceEventRecord:
    return SourceEventRecord(event(), 2, (("event_id", "TEST_EVENT"),))


def intent_record() -> OrderIntentRecord:
    return OrderIntentRecord(
        "intent",
        "TEST_EVENT",
        "decision",
        READY_TIME,
        "{}",
        HASH,
        OrderIntentState.RESERVED,
    )


def entry_record() -> JournalEntryRecord:
    return JournalEntryRecord(
        1,
        "entry",
        JournalEntryKind.DECISION,
        READY_TIME,
        "TEST_EVENT",
        "decision",
        None,
        HASH,
        "test-version",
        "{}",
        HASH,
        HASH,
        HASH,
    )


class Phase3RecordValidationTests(TestCase):
    def test_source_record_rejects_invalid_row_and_fields(self) -> None:
        cases = (
            {"source_row_number": 1},
            {"raw_fields": ()},
            {"raw_fields": (("", "value"),)},
            {"raw_fields": (("name", "one"), ("name", "two"))},
            {"raw_fields": cast(Any, (("name", 1),))},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(source_record(), **changes)

    def test_order_intent_record_rejects_invalid_identity_time_json_and_hash(self) -> None:
        cases = (
            {"idempotency_key": ""},
            {"created_at": datetime(2030, 1, 10, 13, 30)},
            {"plan_json": ""},
            {"plan_hash": "invalid"},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(intent_record(), **changes)

    def test_journal_entry_record_rejects_invalid_sequence_content_time_and_hashes(self) -> None:
        cases = (
            {"sequence": 0},
            {"entry_id": ""},
            {"software_version": ""},
            {"payload_json": ""},
            {"occurred_at": datetime(2030, 1, 10, 13, 30)},
            {"payload_hash": "invalid"},
            {"configuration_hash": "invalid"},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(entry_record(), **changes)

    def test_broker_lookup_requires_consistent_identity_and_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "reason"):
            BrokerOrderLookup(BrokerOrderState.UNKNOWN, None, "")
        with self.assertRaisesRegex(ValueError, "broker_order_id"):
            BrokerOrderLookup(BrokerOrderState.FOUND_OPEN, None, "found")
        with self.assertRaisesRegex(ValueError, "must not invent"):
            BrokerOrderLookup(BrokerOrderState.NOT_FOUND, "invented", "not found")

    def test_submission_result_requires_code_message_and_accepted_order_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "code and message"):
            DurableSubmissionResult(False, "", "message", None, True)
        with self.assertRaisesRegex(ValueError, "broker_order_id"):
            DurableSubmissionResult(True, "ACCEPTED", "accepted", None, False)

    def test_restart_report_never_auto_arms_or_approves_unresolved_intents(self) -> None:
        with self.assertRaisesRegex(ValueError, "never auto-arm"):
            RestartReconciliationReport((), (), True, auto_demo_armed=True)
        with self.assertRaisesRegex(ValueError, "unresolved"):
            RestartReconciliationReport((), ("intent",), True)
