"""Persistence, integrity, audit, and failure tests for the SQLite journal."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from json import loads
from pathlib import Path
from sqlite3 import IntegrityError, connect
from tempfile import TemporaryDirectory
from unittest import TestCase

from catalyst.adapters.sqlite_journal import (
    JournalConflictError,
    JournalIntegrityError,
    JournalLockedError,
    JournalUnavailableError,
    SQLiteJournal,
)
from catalyst.domain.enums import ReasonCode, SystemState
from catalyst.domain.serialization import sha256_canonical
from catalyst.engine.pipeline import DecisionPipeline
from catalyst.ports.event_feed import SourceEventRecord
from catalyst.ports.journal import JournalEntryKind, OrderIntentState
from tests.fixtures import READY_TIME, broker_contract, demo_account, event, long_market

SOFTWARE_VERSION = "test-phase-3"


def source_record(*, ingested_at: datetime | None = None) -> SourceEventRecord:
    normalized = event()
    if ingested_at is not None:
        normalized = replace(normalized, ingested_at=ingested_at)
    return SourceEventRecord(
        event=normalized,
        source_row_number=2,
        raw_fields=(
            ("event_id", normalized.event_id),
            ("name", normalized.name),
            ("scheduled_at", "2030-01-10T13:30:00Z"),
            ("currency", "USD"),
            ("importance", "HIGH"),
            ("status", "SCHEDULED"),
            ("eligible_symbols", "US100"),
            ("source", "test_fixture"),
        ),
    )


def ready_decision():
    return DecisionPipeline().evaluate(
        event(),
        long_market(),
        demo_account(),
        READY_TIME,
        contract=broker_contract(),
        auto_demo_armed=True,
    )


class SQLiteJournalTests(TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "catalyst.sqlite3"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def open(self) -> SQLiteJournal:
        return SQLiteJournal.open(self.path, software_version=SOFTWARE_VERSION)

    def test_opens_with_migration_wal_and_single_instance_lock(self) -> None:
        first = self.open()
        self.addCleanup(first.close)

        self.assertTrue(first.healthy)
        self.assertTrue(first.wal_mode)
        self.assertEqual(first.schema_version, 1)
        with self.assertRaises(JournalLockedError):
            self.open()

        first.close()
        reopened = self.open()
        reopened.close()

    def test_open_rejects_missing_version_and_non_durable_memory_database(self) -> None:
        with self.assertRaisesRegex(ValueError, "software_version"):
            SQLiteJournal.open(self.path, software_version="")
        with self.assertRaisesRegex(ValueError, "durable filesystem"):
            SQLiteJournal.open(":memory:", software_version=SOFTWARE_VERSION)

    def test_repeated_event_import_is_idempotent_across_ingestion_times(self) -> None:
        with self.open() as journal:
            self.assertTrue(journal.record_event(source_record()))
            repeated = source_record(ingested_at=event().ingested_at + timedelta(hours=1))
            self.assertFalse(journal.record_event(repeated))
            self.assertEqual(len(journal.entries_for_event(event().event_id)), 1)

    def test_changed_source_row_under_same_event_id_is_a_conflict(self) -> None:
        original = source_record()
        changed = replace(
            original,
            raw_fields=(*original.raw_fields, ("revision", "unexpected")),
        )
        with self.open() as journal:
            journal.record_event(original)
            with self.assertRaisesRegex(JournalConflictError, "different source row"):
                journal.record_event(changed)

    def test_same_source_row_cannot_normalize_to_changed_event_content(self) -> None:
        original = source_record()
        changed = replace(original, event=replace(original.event, name="Changed release"))
        with self.open() as journal:
            journal.record_event(original)
            with self.assertRaisesRegex(JournalConflictError, "different event content"):
                journal.record_event(changed)

    def test_sensitive_event_source_field_is_rejected(self) -> None:
        original = source_record()
        sensitive = replace(
            original,
            raw_fields=(*original.raw_fields, ("access_token", "must-not-be-stored")),
        )
        with self.open() as journal, self.assertRaisesRegex(ValueError, "sensitive field"):
            journal.record_event(sensitive)

    def test_decision_order_fill_state_and_audit_bundle_are_complete(self) -> None:
        decision = ready_decision()
        assert decision.plan is not None
        with self.open() as journal:
            journal.record_event(source_record())
            journal.record_decision(
                event_id=event().event_id,
                decision_id=decision.plan.decision_id,
                decision=decision,
                occurred_at=READY_TIME,
            )
            journal.record_state_transition(
                event_id=event().event_id,
                decision_id=decision.plan.decision_id,
                state_before=SystemState.WAITING_RETEST,
                state_after=SystemState.READY,
                code=ReasonCode.STATE_READY,
                reason="all gates passed",
                occurred_at=READY_TIME,
            )
            self.assertTrue(journal.reserve_order_intent(decision.plan, READY_TIME))
            self.assertFalse(journal.reserve_order_intent(decision.plan, READY_TIME))
            journal.record_order_state(
                idempotency_key=decision.plan.decision_id,
                event_id=event().event_id,
                decision_id=decision.plan.decision_id,
                state=OrderIntentState.SUBMITTING,
                occurred_at=READY_TIME,
                details={"code": "SUBMISSION_STARTED"},
            )
            journal.record_order_state(
                idempotency_key=decision.plan.decision_id,
                event_id=event().event_id,
                decision_id=decision.plan.decision_id,
                state=OrderIntentState.ACKNOWLEDGED,
                occurred_at=READY_TIME + timedelta(milliseconds=1),
                details={"broker_order_id": "DEMO-1", "code": "ACCEPTED"},
            )
            journal.record_fill(
                event_id=event().event_id,
                decision_id=decision.plan.decision_id,
                idempotency_key=decision.plan.decision_id,
                occurred_at=READY_TIME + timedelta(milliseconds=2),
                fill={"price": "101.2", "quantity": str(decision.plan.quantity)},
            )
            journal.record_heartbeat(
                component="journal",
                status="healthy",
                occurred_at=READY_TIME,
            )

            bundle = loads(journal.export_event_audit_bundle(event().event_id))

            self.assertEqual(bundle["payload"]["schema_version"], "catalyst.audit.v1")
            self.assertEqual(
                bundle["payload"]["event"]["raw_row"]["fields"][0],
                ["event_id", "TEST_EVENT"],
            )
            kinds = [entry["kind"] for entry in bundle["payload"]["entries"]]
            self.assertEqual(
                kinds,
                ["event", "decision", "state_transition", "order", "order", "order", "fill"],
            )
            decision_payload = bundle["payload"]["entries"][1]["payload"]["decision"]
            self.assertEqual(decision_payload["setup"]["catalyst"]["code"], "CATALYST_PASS")
            self.assertTrue(
                all(
                    entry["software_version"] == SOFTWARE_VERSION
                    for entry in bundle["payload"]["entries"]
                )
            )
            self.assertEqual(len(bundle["payload"]["order_intents"]), 1)
            self.assertEqual(bundle["bundle_hash"], sha256_canonical(bundle["payload"]))
            self.assertFalse(
                journal.order_intent_requires_reconciliation(decision.plan.decision_id)
            )
            journal.verify_integrity()

    def test_secret_shaped_payload_is_rejected_without_append(self) -> None:
        with self.open() as journal:
            with self.assertRaisesRegex(ValueError, "sensitive field"):
                journal.record_heartbeat(
                    component="broker",
                    status="healthy",
                    occurred_at=READY_TIME,
                    details={"api_key": "must-not-be-stored"},
                )
            self.assertTrue(journal.healthy)

    def test_nested_secret_and_invalid_heartbeat_or_state_are_rejected(self) -> None:
        with self.open() as journal:
            with self.assertRaisesRegex(ValueError, "sensitive field"):
                journal.record_heartbeat(
                    component="broker",
                    status="healthy",
                    occurred_at=READY_TIME,
                    details={"items": [{"refresh_token": "hidden"}]},
                )
            with self.assertRaisesRegex(ValueError, "component and status"):
                journal.record_heartbeat(
                    component="",
                    status="healthy",
                    occurred_at=READY_TIME,
                )
            with self.assertRaisesRegex(ValueError, "reason"):
                journal.record_state_transition(
                    event_id=None,
                    decision_id=None,
                    state_before=SystemState.SLEEPING,
                    state_after=SystemState.ARMED,
                    code=ReasonCode.STATE_ARMED,
                    reason="",
                    occurred_at=READY_TIME,
                )

    def test_duplicate_entry_is_idempotent_and_identifiers_are_strict(self) -> None:
        with self.open() as journal:
            self.assertTrue(
                journal.record_heartbeat(
                    component="journal",
                    status="healthy",
                    occurred_at=READY_TIME,
                )
            )
            self.assertFalse(
                journal.record_heartbeat(
                    component="journal",
                    status="healthy",
                    occurred_at=READY_TIME,
                )
            )
            with self.assertRaisesRegex(ValueError, "event_id"):
                journal.append_entry(
                    kind=JournalEntryKind.HEARTBEAT,
                    occurred_at=READY_TIME,
                    payload={"status": "healthy"},
                    event_id="",
                )
            with self.assertRaisesRegex(ValueError, "configuration_hash"):
                journal.append_entry(
                    kind=JournalEntryKind.HEARTBEAT,
                    occurred_at=READY_TIME,
                    payload={"status": "healthy"},
                    configuration_hash="invalid",
                )
            with self.assertRaisesRegex(ValueError, "normalized to UTC"):
                journal.record_heartbeat(
                    component="journal",
                    status="healthy",
                    occurred_at=datetime(
                        2030,
                        1,
                        10,
                        14,
                        30,
                        tzinfo=timezone(timedelta(hours=1)),
                    ),
                )

    def test_order_intent_requires_an_ingested_event(self) -> None:
        decision = ready_decision()
        assert decision.plan is not None
        with (
            self.open() as journal,
            self.assertRaisesRegex(JournalConflictError, "event must be journaled"),
        ):
            journal.reserve_order_intent(decision.plan, READY_TIME)

    def test_decision_identity_must_match_trade_plan(self) -> None:
        decision = ready_decision()
        assert decision.plan is not None
        with self.open() as journal:
            journal.record_event(source_record())
            with self.assertRaisesRegex(ValueError, "must match"):
                journal.record_decision(
                    event_id=event().event_id,
                    decision_id="different",
                    decision=decision,
                    occurred_at=READY_TIME,
                )
            with self.assertRaisesRegex(ValueError, "event_id must match"):
                journal.record_decision(
                    event_id="OTHER_EVENT",
                    decision_id=decision.plan.decision_id,
                    decision=decision,
                    occurred_at=READY_TIME,
                )

    def test_first_order_reservation_must_match_the_journaled_decision(self) -> None:
        decision = ready_decision()
        assert decision.plan is not None
        changed = replace(decision.plan, quantity=decision.plan.quantity / 2)
        with self.open() as journal:
            journal.record_event(source_record())
            journal.record_decision(
                event_id=event().event_id,
                decision_id=decision.plan.decision_id,
                decision=decision,
                occurred_at=READY_TIME,
            )
            with self.assertRaisesRegex(JournalConflictError, "journaled decision"):
                journal.reserve_order_intent(changed, READY_TIME)
            self.assertEqual(journal.unresolved_order_intents(), ())

    def test_same_idempotency_key_cannot_change_plan(self) -> None:
        decision = ready_decision()
        assert decision.plan is not None
        changed = replace(decision.plan, quantity=decision.plan.quantity / 2)
        with self.open() as journal:
            journal.record_event(source_record())
            journal.record_decision(
                event_id=event().event_id,
                decision_id=decision.plan.decision_id,
                decision=decision,
                occurred_at=READY_TIME,
            )
            journal.reserve_order_intent(decision.plan, READY_TIME)
            with self.assertRaisesRegex(JournalConflictError, "plan"):
                journal.reserve_order_intent(changed, READY_TIME)

    def test_order_intent_requires_a_journaled_decision(self) -> None:
        decision = ready_decision()
        assert decision.plan is not None
        with self.open() as journal:
            journal.record_event(source_record())
            with self.assertRaisesRegex(JournalConflictError, "decision must be journaled"):
                journal.reserve_order_intent(decision.plan, READY_TIME)

    def test_order_state_requires_intent_matching_ids_and_valid_transition(self) -> None:
        decision = ready_decision()
        assert decision.plan is not None
        with self.open() as journal:
            journal.record_event(source_record())
            journal.record_decision(
                event_id=event().event_id,
                decision_id=decision.plan.decision_id,
                decision=decision,
                occurred_at=READY_TIME,
            )
            with self.assertRaisesRegex(JournalConflictError, "no durable reserved"):
                journal.record_order_state(
                    idempotency_key="missing",
                    event_id=event().event_id,
                    decision_id=decision.plan.decision_id,
                    state=OrderIntentState.SUBMITTING,
                    occurred_at=READY_TIME,
                    details={},
                )
            journal.reserve_order_intent(decision.plan, READY_TIME)
            with self.assertRaisesRegex(JournalConflictError, "identifiers"):
                journal.record_fill(
                    event_id="OTHER_EVENT",
                    decision_id=decision.plan.decision_id,
                    idempotency_key=decision.plan.decision_id,
                    occurred_at=READY_TIME,
                    fill={"price": "101.2", "quantity": "0.1"},
                )
            with self.assertRaisesRegex(JournalConflictError, "identifiers"):
                journal.record_order_state(
                    idempotency_key=decision.plan.decision_id,
                    event_id="OTHER_EVENT",
                    decision_id=decision.plan.decision_id,
                    state=OrderIntentState.SUBMITTING,
                    occurred_at=READY_TIME,
                    details={},
                )
            with self.assertRaisesRegex(ValueError, "reconciliation can only"):
                journal.record_reconciliation_state(
                    idempotency_key=decision.plan.decision_id,
                    event_id=event().event_id,
                    decision_id=decision.plan.decision_id,
                    state=OrderIntentState.ACKNOWLEDGED,
                    occurred_at=READY_TIME,
                    details={},
                )
            journal.record_order_state(
                idempotency_key=decision.plan.decision_id,
                event_id=event().event_id,
                decision_id=decision.plan.decision_id,
                state=OrderIntentState.SUBMITTING,
                occurred_at=READY_TIME,
                details={},
            )
            journal.record_order_state(
                idempotency_key=decision.plan.decision_id,
                event_id=event().event_id,
                decision_id=decision.plan.decision_id,
                state=OrderIntentState.REJECTED,
                occurred_at=READY_TIME + timedelta(milliseconds=1),
                details={},
            )
            with self.assertRaisesRegex(JournalConflictError, "invalid append-only"):
                journal.record_order_state(
                    idempotency_key=decision.plan.decision_id,
                    event_id=event().event_id,
                    decision_id=decision.plan.decision_id,
                    state=OrderIntentState.UNCERTAIN,
                    occurred_at=READY_TIME + timedelta(milliseconds=2),
                    details={},
                )

    def test_unknown_intent_and_missing_audit_event_fail_closed(self) -> None:
        with self.open() as journal:
            self.assertTrue(journal.order_intent_requires_reconciliation("unknown"))
            with self.assertRaises(LookupError):
                journal.export_event_audit_bundle("UNKNOWN_EVENT")

    def test_database_triggers_reject_update_and_delete(self) -> None:
        with self.open() as journal:
            journal.record_event(source_record())
        connection = connect(self.path)
        self.addCleanup(connection.close)
        with self.assertRaisesRegex(IntegrityError, "append-only"):
            connection.execute(
                "UPDATE event_records SET source = 'changed' WHERE event_id = ?",
                (event().event_id,),
            )
        with self.assertRaisesRegex(IntegrityError, "append-only"):
            connection.execute(
                "DELETE FROM journal_entries WHERE event_id = ?",
                (event().event_id,),
            )

    def test_migration_checksum_mismatch_fails_closed(self) -> None:
        connection = connect(self.path)
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES (1, 'phase_3_append_only_journal', ?)",
            ("0" * 64,),
        )
        connection.commit()
        connection.close()

        with self.assertRaisesRegex(JournalIntegrityError, "checksum"):
            self.open()

    def test_unknown_migration_version_fails_closed(self) -> None:
        connection = connect(self.path)
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, checksum TEXT)"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES (99, 'future', ?)",
            ("0" * 64,),
        )
        connection.commit()
        connection.close()

        with self.assertRaisesRegex(JournalIntegrityError, "unsupported migration"):
            self.open()

    def test_tampered_user_version_and_missing_trigger_fail_closed(self) -> None:
        with self.open():
            pass
        connection = connect(self.path)
        connection.execute("PRAGMA user_version = 0")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(JournalIntegrityError, "user_version"):
            self.open()

        connection = connect(self.path)
        connection.execute("PRAGMA user_version = 1")
        connection.execute("DROP TRIGGER event_records_no_delete")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(JournalIntegrityError, "schema objects"):
            self.open()

    def test_non_sqlite_file_fails_closed(self) -> None:
        self.path.write_bytes(b"not a sqlite database")
        with self.assertRaises(JournalUnavailableError):
            self.open()

    def test_hash_tampering_is_detected_on_restart(self) -> None:
        with self.open() as journal:
            journal.record_event(source_record())
        connection = connect(self.path)
        connection.execute("DROP TRIGGER journal_entries_no_update")
        connection.execute("UPDATE journal_entries SET payload_json = '{}' WHERE sequence = 1")
        connection.execute(
            """
            CREATE TRIGGER journal_entries_no_update
            BEFORE UPDATE ON journal_entries
            BEGIN
                SELECT RAISE(ABORT, 'journal_entries are append-only');
            END
            """
        )
        connection.commit()
        connection.close()

        with self.assertRaisesRegex(JournalIntegrityError, "payload hash"):
            self.open()

    def test_closed_journal_disarms_writes(self) -> None:
        journal = self.open()
        journal.close()
        self.assertFalse(journal.healthy)
        with self.assertRaisesRegex(JournalUnavailableError, "closed|health"):
            journal.record_event(source_record())
