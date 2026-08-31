"""Checksummed, append-only SQLite journal with durable order idempotency."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from json import loads
from pathlib import Path
from re import fullmatch
from sqlite3 import Connection, DatabaseError, IntegrityError, Row, connect
from types import TracebackType
from typing import Any

from catalyst.domain.enums import ReasonCode, SystemState
from catalyst.domain.models import PipelineDecision, TradePlan
from catalyst.domain.serialization import canonical_json, sha256_canonical, to_canonical_value
from catalyst.ports.event_feed import SourceEventRecord
from catalyst.ports.journal import (
    JournalEntryKind,
    JournalEntryRecord,
    OrderIntentRecord,
    OrderIntentState,
)

ZERO_HASH = "0" * 64
_TERMINAL_ORDER_STATES = {
    OrderIntentState.ACKNOWLEDGED,
    OrderIntentState.REJECTED,
    OrderIntentState.RECONCILED,
}
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "auth_token",
    "authorization",
    "credential",
    "private_key",
    "session_cookie",
    "account_login",
)
_REQUIRED_SCHEMA_OBJECTS = {
    ("index", "journal_decision_identity"),
    ("index", "journal_entries_event_sequence"),
    ("index", "journal_entries_intent_sequence"),
    ("table", "event_records"),
    ("table", "journal_entries"),
    ("table", "order_intents"),
    ("table", "schema_migrations"),
    ("trigger", "event_records_no_delete"),
    ("trigger", "event_records_no_update"),
    ("trigger", "journal_entries_no_delete"),
    ("trigger", "journal_entries_no_update"),
    ("trigger", "order_intents_no_delete"),
    ("trigger", "order_intents_no_update"),
    ("trigger", "schema_migrations_no_delete"),
    ("trigger", "schema_migrations_no_update"),
}


class JournalError(RuntimeError):
    """Base class for journal failures that must keep execution disarmed."""


class JournalLockedError(JournalError):
    """Raised when another process already owns the journal lock."""


class JournalIntegrityError(JournalError):
    """Raised when schema, hashes, or immutable state cannot be trusted."""


class JournalConflictError(JournalError):
    """Raised when an existing identity is presented with different content."""


class JournalUnavailableError(JournalError):
    """Raised when SQLite cannot be opened or written safely."""


@dataclass(frozen=True, slots=True)
class _Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        return sha256("\n".join(self.statements).encode("utf-8")).hexdigest()


_MIGRATIONS = (
    _Migration(
        1,
        "phase_3_append_only_journal",
        (
            """
            CREATE TABLE event_records (
                event_id TEXT PRIMARY KEY,
                scheduled_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                source TEXT NOT NULL,
                source_row_number INTEGER NOT NULL CHECK (source_row_number >= 2),
                raw_row_json TEXT NOT NULL,
                raw_hash TEXT NOT NULL CHECK (length(raw_hash) = 64),
                normalized_event_json TEXT NOT NULL,
                normalized_hash TEXT NOT NULL CHECK (length(normalized_hash) = 64)
            )
            """,
            """
            CREATE TRIGGER event_records_no_update
            BEFORE UPDATE ON event_records
            BEGIN
                SELECT RAISE(ABORT, 'event_records are append-only');
            END
            """,
            """
            CREATE TRIGGER event_records_no_delete
            BEFORE DELETE ON event_records
            BEGIN
                SELECT RAISE(ABORT, 'event_records are append-only');
            END
            """,
            """
            CREATE TABLE order_intents (
                idempotency_key TEXT PRIMARY KEY,
                event_id TEXT NOT NULL REFERENCES event_records(event_id),
                decision_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                configuration_hash TEXT NOT NULL CHECK (length(configuration_hash) = 64),
                plan_json TEXT NOT NULL,
                plan_hash TEXT NOT NULL CHECK (length(plan_hash) = 64)
            )
            """,
            """
            CREATE TRIGGER order_intents_no_update
            BEFORE UPDATE ON order_intents
            BEGIN
                SELECT RAISE(ABORT, 'order_intents are append-only');
            END
            """,
            """
            CREATE TRIGGER order_intents_no_delete
            BEFORE DELETE ON order_intents
            BEGIN
                SELECT RAISE(ABORT, 'order_intents are append-only');
            END
            """,
            """
            CREATE TABLE journal_entries (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id TEXT NOT NULL UNIQUE,
                entry_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                event_id TEXT REFERENCES event_records(event_id),
                decision_id TEXT,
                idempotency_key TEXT REFERENCES order_intents(idempotency_key),
                configuration_hash TEXT,
                software_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
                previous_hash TEXT NOT NULL CHECK (length(previous_hash) = 64),
                entry_hash TEXT NOT NULL UNIQUE CHECK (length(entry_hash) = 64)
            )
            """,
            """
            CREATE INDEX journal_entries_event_sequence
            ON journal_entries(event_id, sequence)
            """,
            """
            CREATE INDEX journal_entries_intent_sequence
            ON journal_entries(idempotency_key, sequence)
            """,
            """
            CREATE UNIQUE INDEX journal_decision_identity
            ON journal_entries(decision_id)
            WHERE entry_type = 'decision'
            """,
            """
            CREATE TRIGGER journal_entries_no_update
            BEFORE UPDATE ON journal_entries
            BEGIN
                SELECT RAISE(ABORT, 'journal_entries are append-only');
            END
            """,
            """
            CREATE TRIGGER journal_entries_no_delete
            BEFORE DELETE ON journal_entries
            BEGIN
                SELECT RAISE(ABORT, 'journal_entries are append-only');
            END
            """,
            """
            CREATE TRIGGER schema_migrations_no_update
            BEFORE UPDATE ON schema_migrations
            BEGIN
                SELECT RAISE(ABORT, 'schema_migrations are append-only');
            END
            """,
            """
            CREATE TRIGGER schema_migrations_no_delete
            BEFORE DELETE ON schema_migrations
            BEGIN
                SELECT RAISE(ABORT, 'schema_migrations are append-only');
            END
            """,
        ),
    ),
)


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be normalized to UTC")


def _utc_text(value: datetime, field_name: str) -> str:
    _require_utc(value, field_name)
    return value.isoformat().replace("+00:00", "Z")


def _parse_utc(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JournalIntegrityError(f"stored {field_name} is not ISO-8601") from exc
    _require_utc(parsed, field_name)
    return parsed.astimezone(UTC)


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _require_identifier(value: str | None, field_name: str) -> None:
    if value is not None and not value.strip():
        raise ValueError(f"{field_name} must not be empty when present")


def _reject_secret_keys(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.lower().replace("-", "_").replace(" ", "_")
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                raise ValueError(f"journal payload contains sensitive field at {path}.{key}")
            _reject_secret_keys(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_keys(item, f"{path}[{index}]")


class _SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(  # type: ignore[attr-defined]
                    handle.fileno(),
                    msvcrt.LK_NBLCK,  # type: ignore[attr-defined]
                    1,
                )
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise JournalLockedError(f"journal is already locked: {self.path}") from exc
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(  # type: ignore[attr-defined]
                    self._handle.fileno(),
                    msvcrt.LK_UNLCK,  # type: ignore[attr-defined]
                    1,
                )
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


class SQLiteJournal:
    """One-process SQLite journal whose business records can only be appended."""

    def __init__(
        self,
        path: Path,
        software_version: str,
        connection: Connection,
        lock: _SingleInstanceLock,
    ) -> None:
        self.path = path
        self.software_version = software_version
        self._connection: Connection | None = connection
        self._lock = lock
        self._healthy = False

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        software_version: str,
    ) -> SQLiteJournal:
        if not software_version.strip():
            raise ValueError("software_version must not be empty")
        database_path = Path(path)
        if str(database_path) == ":memory:":
            raise ValueError("journal must use a durable filesystem path")
        database_path.parent.mkdir(parents=True, exist_ok=True)
        lock = _SingleInstanceLock(database_path.with_name(database_path.name + ".lock"))
        lock.acquire()
        connection: Connection | None = None
        try:
            connection = connect(database_path, isolation_level=None, timeout=5)
            connection.row_factory = Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0])
            if mode.lower() != "wal":
                raise JournalIntegrityError("SQLite journal did not enter WAL mode")
            connection.execute("PRAGMA synchronous = FULL")
            journal = cls(database_path, software_version, connection, lock)
            journal._apply_migrations()
            journal.verify_integrity()
            journal._healthy = True
            return journal
        except JournalError:
            if connection is not None:
                connection.close()
            lock.release()
            raise
        except DatabaseError as exc:
            if connection is not None:
                connection.close()
            lock.release()
            raise JournalUnavailableError("SQLite journal could not be opened safely") from exc
        except Exception:
            if connection is not None:
                connection.close()
            lock.release()
            raise

    @property
    def healthy(self) -> bool:
        return self._healthy and self._connection is not None

    @property
    def schema_version(self) -> int:
        connection = self._require_connection()
        return int(connection.execute("PRAGMA user_version").fetchone()[0])

    @property
    def wal_mode(self) -> bool:
        connection = self._require_connection()
        mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        return mode.lower() == "wal"

    def __enter__(self) -> SQLiteJournal:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._healthy = False
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._lock.release()

    def _require_connection(self) -> Connection:
        if self._connection is None:
            raise JournalUnavailableError("journal is closed")
        return self._connection

    def _require_healthy(self) -> Connection:
        if not self.healthy:
            raise JournalUnavailableError("journal health is unknown; execution must stay disarmed")
        return self._require_connection()

    @contextmanager
    def _transaction(self) -> Iterator[Connection]:
        connection = self._require_healthy()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except DatabaseError as exc:
            if connection.in_transaction:
                with suppress(DatabaseError):
                    connection.execute("ROLLBACK")
            self._healthy = False
            raise JournalUnavailableError(
                "journal write failed; execution must stay disarmed"
            ) from exc
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _apply_migrations(self) -> None:
        connection = self._require_connection()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL CHECK (length(checksum) = 64)
                )
                """
            )
            applied = {
                int(row["version"]): (str(row["name"]), str(row["checksum"]))
                for row in connection.execute(
                    "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
                )
            }
            known = {migration.version: migration for migration in _MIGRATIONS}
            unknown = sorted(set(applied) - set(known))
            if unknown:
                raise JournalIntegrityError(
                    f"journal has unsupported migration versions: {unknown}"
                )
            for version, (name, checksum) in applied.items():
                migration = known[version]
                if name != migration.name or checksum != migration.checksum:
                    raise JournalIntegrityError(
                        f"journal migration {version} checksum or name does not match"
                    )
            current_user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if applied and current_user_version != max(applied):
                raise JournalIntegrityError(
                    "journal user_version does not match its applied migrations"
                )
            if not applied and current_user_version != 0:
                raise JournalIntegrityError("unmigrated journal has a non-zero user_version")

            connection.execute("BEGIN EXCLUSIVE")
            for migration in _MIGRATIONS:
                if migration.version in applied:
                    continue
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, checksum) VALUES (?, ?, ?)",
                    (migration.version, migration.name, migration.checksum),
                )
            connection.execute(f"PRAGMA user_version = {_MIGRATIONS[-1].version}")
            connection.execute("COMMIT")
        except JournalError:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        except DatabaseError as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise JournalIntegrityError("journal schema migration failed") from exc

    def record_event(self, record: SourceEventRecord) -> bool:
        normalized_json = canonical_json(record.event)
        raw_json = canonical_json({"fields": record.raw_fields})
        _reject_secret_keys(to_canonical_value(record.raw_mapping()), "event_source")
        with self._transaction() as connection:
            existing = connection.execute(
                """
                SELECT raw_hash, normalized_event_json
                FROM event_records
                WHERE event_id = ?
                """,
                (record.event.event_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["raw_hash"]) != record.raw_hash:
                    raise JournalConflictError(
                        "event_id already exists with a different source row"
                    )
                old_normalized = loads(str(existing["normalized_event_json"]))
                new_normalized = loads(normalized_json)
                old_normalized.pop("ingested_at", None)
                new_normalized.pop("ingested_at", None)
                if old_normalized != new_normalized:
                    raise JournalConflictError(
                        "event_id source row now normalizes to different event content"
                    )
                return False
            try:
                connection.execute(
                    """
                    INSERT INTO event_records(
                        event_id, scheduled_at, ingested_at, source, source_row_number,
                        raw_row_json, raw_hash, normalized_event_json, normalized_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.event.event_id,
                        _utc_text(record.event.scheduled_at, "scheduled_at"),
                        _utc_text(record.event.ingested_at, "ingested_at"),
                        record.event.source,
                        record.source_row_number,
                        raw_json,
                        record.raw_hash,
                        normalized_json,
                        record.normalized_hash,
                    ),
                )
                self._append_entry_locked(
                    connection,
                    kind=JournalEntryKind.EVENT,
                    occurred_at=record.event.ingested_at,
                    payload={
                        "event_id": record.event.event_id,
                        "normalized_hash": record.normalized_hash,
                        "raw_hash": record.raw_hash,
                        "source_row_number": record.source_row_number,
                    },
                    event_id=record.event.event_id,
                )
            except IntegrityError as exc:
                raise JournalConflictError("event record could not be appended") from exc
        return True

    def record_decision(
        self,
        *,
        event_id: str,
        decision_id: str,
        decision: PipelineDecision,
        occurred_at: datetime,
    ) -> bool:
        if decision.plan is not None and decision.plan.decision_id != decision_id:
            raise ValueError("decision_id must match the trade plan")
        if decision.plan is not None and decision.plan.event_id != event_id:
            raise ValueError("event_id must match the trade plan")
        return self.append_entry(
            kind=JournalEntryKind.DECISION,
            occurred_at=occurred_at,
            payload={"decision": decision},
            event_id=event_id,
            decision_id=decision_id,
            configuration_hash=decision.configuration_hash,
        )

    def reserve_order_intent(self, plan: TradePlan, occurred_at: datetime) -> bool:
        _require_utc(occurred_at, "occurred_at")
        plan_json = canonical_json(plan)
        plan_hash = _hash_text(plan_json)
        with self._transaction() as connection:
            event_exists = connection.execute(
                "SELECT 1 FROM event_records WHERE event_id = ?",
                (plan.event_id,),
            ).fetchone()
            if event_exists is None:
                raise JournalConflictError(
                    "event must be journaled before its order intent is reserved"
                )
            decision_row = connection.execute(
                """
                SELECT configuration_hash, payload_json
                FROM journal_entries
                WHERE entry_type = ? AND event_id = ? AND decision_id = ?
                """,
                (JournalEntryKind.DECISION.value, plan.event_id, plan.decision_id),
            ).fetchone()
            if decision_row is None:
                raise JournalConflictError(
                    "decision must be journaled before its order intent is reserved"
                )
            try:
                recorded_plan = loads(str(decision_row["payload_json"]))["decision"]["plan"]
            except (KeyError, TypeError) as exc:
                raise JournalIntegrityError(
                    "journaled decision does not contain a trade plan"
                ) from exc
            if (
                canonical_json(recorded_plan) != plan_json
                or str(decision_row["configuration_hash"]) != plan.configuration_hash
            ):
                raise JournalConflictError(
                    "order intent plan does not match its journaled decision"
                )
            existing = connection.execute(
                """
                SELECT event_id, decision_id, plan_hash
                FROM order_intents
                WHERE idempotency_key = ?
                """,
                (plan.decision_id,),
            ).fetchone()
            if existing is not None:
                matches = (
                    str(existing["event_id"]) == plan.event_id
                    and str(existing["decision_id"]) == plan.decision_id
                    and str(existing["plan_hash"]) == plan_hash
                )
                if not matches:
                    raise JournalConflictError(
                        "idempotency key already exists with a different trade plan"
                    )
                return False
            try:
                connection.execute(
                    """
                    INSERT INTO order_intents(
                        idempotency_key, event_id, decision_id, created_at,
                        configuration_hash, plan_json, plan_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan.decision_id,
                        plan.event_id,
                        plan.decision_id,
                        _utc_text(occurred_at, "occurred_at"),
                        plan.configuration_hash,
                        plan_json,
                        plan_hash,
                    ),
                )
                self._append_entry_locked(
                    connection,
                    kind=JournalEntryKind.ORDER,
                    occurred_at=occurred_at,
                    payload={"plan_hash": plan_hash, "state": OrderIntentState.RESERVED},
                    event_id=plan.event_id,
                    decision_id=plan.decision_id,
                    idempotency_key=plan.decision_id,
                    configuration_hash=plan.configuration_hash,
                )
            except IntegrityError as exc:
                raise JournalConflictError(
                    "event must be journaled before its order intent is reserved"
                ) from exc
        return True

    def record_order_state(
        self,
        *,
        idempotency_key: str,
        event_id: str,
        decision_id: str,
        state: OrderIntentState,
        occurred_at: datetime,
        details: Mapping[str, Any],
    ) -> bool:
        return self._record_order_state(
            kind=JournalEntryKind.ORDER,
            idempotency_key=idempotency_key,
            event_id=event_id,
            decision_id=decision_id,
            state=state,
            occurred_at=occurred_at,
            details=details,
        )

    def record_reconciliation_state(
        self,
        *,
        idempotency_key: str,
        event_id: str,
        decision_id: str,
        state: OrderIntentState,
        occurred_at: datetime,
        details: Mapping[str, Any],
    ) -> bool:
        if state not in {OrderIntentState.UNCERTAIN, OrderIntentState.RECONCILED}:
            raise ValueError("reconciliation can only remain uncertain or become reconciled")
        return self._record_order_state(
            kind=JournalEntryKind.RECONCILIATION,
            idempotency_key=idempotency_key,
            event_id=event_id,
            decision_id=decision_id,
            state=state,
            occurred_at=occurred_at,
            details=details,
        )

    def _record_order_state(
        self,
        *,
        kind: JournalEntryKind,
        idempotency_key: str,
        event_id: str,
        decision_id: str,
        state: OrderIntentState,
        occurred_at: datetime,
        details: Mapping[str, Any],
    ) -> bool:
        with self._transaction() as connection:
            intent = connection.execute(
                """
                SELECT event_id, decision_id, configuration_hash
                FROM order_intents
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if intent is None:
                raise JournalConflictError("order state has no durable reserved intent")
            if str(intent["event_id"]) != event_id or str(intent["decision_id"]) != decision_id:
                raise JournalConflictError("order state identifiers do not match the intent")
            current = self._latest_order_state_locked(connection, idempotency_key)
            self._validate_order_transition(current, state)
            return self._append_entry_locked(
                connection,
                kind=kind,
                occurred_at=occurred_at,
                payload={"details": dict(details), "state": state},
                event_id=event_id,
                decision_id=decision_id,
                idempotency_key=idempotency_key,
                configuration_hash=str(intent["configuration_hash"]),
            )

    @staticmethod
    def _validate_order_transition(
        current: OrderIntentState,
        target: OrderIntentState,
    ) -> None:
        allowed = {
            OrderIntentState.RESERVED: {
                OrderIntentState.SUBMITTING,
                OrderIntentState.REJECTED,
                OrderIntentState.UNCERTAIN,
                OrderIntentState.RECONCILED,
            },
            OrderIntentState.SUBMITTING: {
                OrderIntentState.ACKNOWLEDGED,
                OrderIntentState.REJECTED,
                OrderIntentState.UNCERTAIN,
                OrderIntentState.RECONCILED,
            },
            OrderIntentState.UNCERTAIN: {
                OrderIntentState.UNCERTAIN,
                OrderIntentState.RECONCILED,
            },
        }
        if target not in allowed.get(current, set()):
            raise JournalConflictError(
                f"invalid append-only order transition: {current.value} -> {target.value}"
            )

    def record_fill(
        self,
        *,
        event_id: str,
        decision_id: str,
        idempotency_key: str,
        occurred_at: datetime,
        fill: Mapping[str, Any],
    ) -> bool:
        return self.append_entry(
            kind=JournalEntryKind.FILL,
            occurred_at=occurred_at,
            payload={"fill": dict(fill)},
            event_id=event_id,
            decision_id=decision_id,
            idempotency_key=idempotency_key,
        )

    def record_state_transition(
        self,
        *,
        event_id: str | None,
        decision_id: str | None,
        state_before: SystemState,
        state_after: SystemState,
        code: ReasonCode,
        reason: str,
        occurred_at: datetime,
    ) -> bool:
        if not reason.strip():
            raise ValueError("state transition reason must not be empty")
        return self.append_entry(
            kind=JournalEntryKind.STATE_TRANSITION,
            occurred_at=occurred_at,
            payload={
                "code": code,
                "reason": reason,
                "state_after": state_after,
                "state_before": state_before,
            },
            event_id=event_id,
            decision_id=decision_id,
        )

    def record_heartbeat(
        self,
        *,
        component: str,
        status: str,
        occurred_at: datetime,
        details: Mapping[str, Any] | None = None,
    ) -> bool:
        if not component.strip() or not status.strip():
            raise ValueError("heartbeat component and status must not be empty")
        return self.append_entry(
            kind=JournalEntryKind.HEARTBEAT,
            occurred_at=occurred_at,
            payload={
                "component": component,
                "details": dict(details or {}),
                "status": status,
            },
        )

    def append_entry(
        self,
        *,
        kind: JournalEntryKind,
        occurred_at: datetime,
        payload: Mapping[str, Any],
        event_id: str | None = None,
        decision_id: str | None = None,
        idempotency_key: str | None = None,
        configuration_hash: str | None = None,
    ) -> bool:
        with self._transaction() as connection:
            try:
                return self._append_entry_locked(
                    connection,
                    kind=kind,
                    occurred_at=occurred_at,
                    payload=payload,
                    event_id=event_id,
                    decision_id=decision_id,
                    idempotency_key=idempotency_key,
                    configuration_hash=configuration_hash,
                )
            except IntegrityError as exc:
                raise JournalConflictError("journal entry violates a durable identity") from exc

    def _append_entry_locked(
        self,
        connection: Connection,
        *,
        kind: JournalEntryKind,
        occurred_at: datetime,
        payload: Mapping[str, Any],
        event_id: str | None = None,
        decision_id: str | None = None,
        idempotency_key: str | None = None,
        configuration_hash: str | None = None,
    ) -> bool:
        occurred_text = _utc_text(occurred_at, "occurred_at")
        for value, field_name in (
            (event_id, "event_id"),
            (decision_id, "decision_id"),
            (idempotency_key, "idempotency_key"),
        ):
            _require_identifier(value, field_name)
        if (
            configuration_hash is not None
            and fullmatch(r"[0-9a-f]{64}", configuration_hash) is None
        ):
            raise ValueError("configuration_hash must be a lowercase SHA-256 digest")
        if idempotency_key is not None:
            intent = connection.execute(
                """
                SELECT event_id, decision_id, configuration_hash
                FROM order_intents
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if intent is None:
                raise JournalConflictError("journal entry has no durable reserved intent")
            if event_id != str(intent["event_id"]) or decision_id != str(intent["decision_id"]):
                raise JournalConflictError(
                    "journal entry identifiers do not match the reserved intent"
                )
            intent_configuration_hash = str(intent["configuration_hash"])
            if configuration_hash is None:
                configuration_hash = intent_configuration_hash
            elif configuration_hash != intent_configuration_hash:
                raise JournalConflictError(
                    "journal entry configuration does not match the reserved intent"
                )
        canonical_payload = to_canonical_value(dict(payload))
        _reject_secret_keys(canonical_payload)
        payload_json = canonical_json(canonical_payload)
        payload_hash = _hash_text(payload_json)
        descriptor = {
            "configuration_hash": configuration_hash,
            "decision_id": decision_id,
            "event_id": event_id,
            "idempotency_key": idempotency_key,
            "kind": kind,
            "occurred_at": occurred_at,
            "payload_hash": payload_hash,
            "software_version": self.software_version,
        }
        entry_id = sha256_canonical(descriptor)
        existing = connection.execute(
            "SELECT payload_hash FROM journal_entries WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["payload_hash"]) != payload_hash:
                raise JournalConflictError("journal entry ID has conflicting content")
            return False
        previous = connection.execute(
            "SELECT entry_hash FROM journal_entries ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = ZERO_HASH if previous is None else str(previous["entry_hash"])
        entry_hash = sha256_canonical(
            {"descriptor": descriptor, "entry_id": entry_id, "previous_hash": previous_hash}
        )
        connection.execute(
            """
            INSERT INTO journal_entries(
                entry_id, entry_type, occurred_at, event_id, decision_id,
                idempotency_key, configuration_hash, software_version,
                payload_json, payload_hash, previous_hash, entry_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                kind.value,
                occurred_text,
                event_id,
                decision_id,
                idempotency_key,
                configuration_hash,
                self.software_version,
                payload_json,
                payload_hash,
                previous_hash,
                entry_hash,
            ),
        )
        return True

    def _latest_order_state_locked(
        self,
        connection: Connection,
        idempotency_key: str,
    ) -> OrderIntentState:
        row = connection.execute(
            """
            SELECT payload_json
            FROM journal_entries
            WHERE idempotency_key = ?
              AND entry_type IN (?, ?)
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (
                idempotency_key,
                JournalEntryKind.ORDER.value,
                JournalEntryKind.RECONCILIATION.value,
            ),
        ).fetchone()
        if row is None:
            raise JournalIntegrityError("order intent has no append-only lifecycle state")
        try:
            payload = loads(str(row["payload_json"]))
            return OrderIntentState(payload["state"])
        except (KeyError, TypeError, ValueError) as exc:
            raise JournalIntegrityError("order lifecycle state is unknown") from exc

    def unresolved_order_intents(self) -> tuple[OrderIntentRecord, ...]:
        connection = self._require_healthy()
        records: list[OrderIntentRecord] = []
        rows = connection.execute(
            """
            SELECT idempotency_key, event_id, decision_id, created_at, plan_json, plan_hash
            FROM order_intents
            ORDER BY created_at, idempotency_key
            """
        ).fetchall()
        for row in rows:
            key = str(row["idempotency_key"])
            latest = self._latest_order_state_locked(connection, key)
            if latest in _TERMINAL_ORDER_STATES:
                continue
            records.append(self._intent_from_row(row, latest))
        return tuple(records)

    def order_intent_requires_reconciliation(self, idempotency_key: str) -> bool:
        connection = self._require_healthy()
        row = connection.execute(
            "SELECT 1 FROM order_intents WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return True
        return (
            self._latest_order_state_locked(connection, idempotency_key)
            not in _TERMINAL_ORDER_STATES
        )

    @staticmethod
    def _intent_from_row(row: Row, state: OrderIntentState) -> OrderIntentRecord:
        return OrderIntentRecord(
            idempotency_key=str(row["idempotency_key"]),
            event_id=str(row["event_id"]),
            decision_id=str(row["decision_id"]),
            created_at=_parse_utc(str(row["created_at"]), "created_at"),
            plan_json=str(row["plan_json"]),
            plan_hash=str(row["plan_hash"]),
            latest_state=state,
        )

    def entries_for_event(self, event_id: str) -> tuple[JournalEntryRecord, ...]:
        connection = self._require_healthy()
        rows = connection.execute(
            "SELECT * FROM journal_entries WHERE event_id = ? ORDER BY sequence",
            (event_id,),
        ).fetchall()
        return tuple(self._entry_from_row(row) for row in rows)

    @staticmethod
    def _entry_from_row(row: Row) -> JournalEntryRecord:
        return JournalEntryRecord(
            sequence=int(row["sequence"]),
            entry_id=str(row["entry_id"]),
            kind=JournalEntryKind(str(row["entry_type"])),
            occurred_at=_parse_utc(str(row["occurred_at"]), "occurred_at"),
            event_id=None if row["event_id"] is None else str(row["event_id"]),
            decision_id=None if row["decision_id"] is None else str(row["decision_id"]),
            idempotency_key=(
                None if row["idempotency_key"] is None else str(row["idempotency_key"])
            ),
            configuration_hash=(
                None if row["configuration_hash"] is None else str(row["configuration_hash"])
            ),
            software_version=str(row["software_version"]),
            payload_json=str(row["payload_json"]),
            payload_hash=str(row["payload_hash"]),
            previous_hash=str(row["previous_hash"]),
            entry_hash=str(row["entry_hash"]),
        )

    def export_event_audit_bundle(self, event_id: str) -> str:
        self.verify_integrity()
        connection = self._require_healthy()
        event = connection.execute(
            "SELECT * FROM event_records WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if event is None:
            raise LookupError(f"event is not present in the journal: {event_id}")
        order_rows = connection.execute(
            "SELECT * FROM order_intents WHERE event_id = ? ORDER BY created_at, idempotency_key",
            (event_id,),
        ).fetchall()
        entries = self.entries_for_event(event_id)
        payload = {
            "event": {
                "ingested_at": str(event["ingested_at"]),
                "normalized": loads(str(event["normalized_event_json"])),
                "normalized_hash": str(event["normalized_hash"]),
                "raw_hash": str(event["raw_hash"]),
                "raw_row": loads(str(event["raw_row_json"])),
                "scheduled_at": str(event["scheduled_at"]),
                "source": str(event["source"]),
                "source_row_number": int(event["source_row_number"]),
            },
            "entries": [
                {
                    "configuration_hash": entry.configuration_hash,
                    "decision_id": entry.decision_id,
                    "entry_hash": entry.entry_hash,
                    "entry_id": entry.entry_id,
                    "event_id": entry.event_id,
                    "idempotency_key": entry.idempotency_key,
                    "kind": entry.kind,
                    "occurred_at": entry.occurred_at,
                    "payload": loads(entry.payload_json),
                    "payload_hash": entry.payload_hash,
                    "previous_hash": entry.previous_hash,
                    "sequence": entry.sequence,
                    "software_version": entry.software_version,
                }
                for entry in entries
            ],
            "order_intents": [
                {
                    "configuration_hash": str(row["configuration_hash"]),
                    "created_at": str(row["created_at"]),
                    "decision_id": str(row["decision_id"]),
                    "idempotency_key": str(row["idempotency_key"]),
                    "plan": loads(str(row["plan_json"])),
                    "plan_hash": str(row["plan_hash"]),
                }
                for row in order_rows
            ],
            "schema_version": "catalyst.audit.v1",
            "software_version": self.software_version,
            "storage_schema_version": self.schema_version,
        }
        return canonical_json({"bundle_hash": sha256_canonical(payload), "payload": payload})

    def verify_integrity(self) -> None:
        connection = self._require_connection()
        try:
            quick = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            if quick != "ok":
                raise JournalIntegrityError(f"SQLite quick_check failed: {quick}")
            foreign = connection.execute("PRAGMA foreign_key_check").fetchone()
            if foreign is not None:
                raise JournalIntegrityError("SQLite foreign-key check failed")
            mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
            if mode.lower() != "wal":
                raise JournalIntegrityError("SQLite journal is not in WAL mode")
            schema_rows = connection.execute(
                """
                SELECT type, name, sql
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
            schema_objects = {(str(row["type"]), str(row["name"])) for row in schema_rows}
            missing_objects = sorted(_REQUIRED_SCHEMA_OBJECTS - schema_objects)
            if missing_objects:
                raise JournalIntegrityError(
                    f"journal schema objects are missing: {missing_objects}"
                )
            for row in schema_rows:
                if str(row["type"]) == "trigger" and "append-only" not in str(row["sql"]):
                    raise JournalIntegrityError("journal append-only trigger is malformed")
            migrations = {
                int(row["version"]): (str(row["name"]), str(row["checksum"]))
                for row in connection.execute(
                    "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
                )
            }
            if len(migrations) != len(_MIGRATIONS):
                raise JournalIntegrityError("journal migration set is incomplete")
            for migration in _MIGRATIONS:
                if migrations.get(migration.version) != (migration.name, migration.checksum):
                    raise JournalIntegrityError("journal migration checksum does not match")
            user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if user_version != _MIGRATIONS[-1].version:
                raise JournalIntegrityError("journal user_version does not match migrations")

            for row in connection.execute("SELECT * FROM event_records ORDER BY event_id"):
                raw_json = str(row["raw_row_json"])
                normalized_json = str(row["normalized_event_json"])
                if _hash_text(raw_json) != str(row["raw_hash"]):
                    raise JournalIntegrityError("event raw-row hash does not match")
                if _hash_text(normalized_json) != str(row["normalized_hash"]):
                    raise JournalIntegrityError("normalized event hash does not match")
                if canonical_json(loads(raw_json)) != raw_json:
                    raise JournalIntegrityError("event raw-row JSON is not canonical")
                normalized_event = loads(normalized_json)
                if canonical_json(normalized_event) != normalized_json:
                    raise JournalIntegrityError("normalized event JSON is not canonical")
                stored_identity = (
                    str(row["event_id"]),
                    str(row["scheduled_at"]),
                    str(row["ingested_at"]),
                    str(row["source"]),
                )
                normalized_identity = (
                    normalized_event["event_id"],
                    normalized_event["scheduled_at"],
                    normalized_event["ingested_at"],
                    normalized_event["source"],
                )
                if stored_identity != normalized_identity:
                    raise JournalIntegrityError("event index columns do not match normalized JSON")
            for row in connection.execute("SELECT * FROM order_intents"):
                plan_json = str(row["plan_json"])
                if _hash_text(plan_json) != str(row["plan_hash"]):
                    raise JournalIntegrityError("order plan hash does not match")
                plan = loads(plan_json)
                if canonical_json(plan) != plan_json:
                    raise JournalIntegrityError("order plan JSON is not canonical")
                stored_identity = (
                    str(row["idempotency_key"]),
                    str(row["event_id"]),
                    str(row["decision_id"]),
                    str(row["configuration_hash"]),
                )
                plan_identity = (
                    plan["decision_id"],
                    plan["event_id"],
                    plan["decision_id"],
                    plan["configuration_hash"],
                )
                if stored_identity != plan_identity:
                    raise JournalIntegrityError("order intent columns do not match plan JSON")
                decision_row = connection.execute(
                    """
                    SELECT configuration_hash, payload_json
                    FROM journal_entries
                    WHERE entry_type = ? AND event_id = ? AND decision_id = ?
                    """,
                    (
                        JournalEntryKind.DECISION.value,
                        row["event_id"],
                        row["decision_id"],
                    ),
                ).fetchone()
                if decision_row is None:
                    raise JournalIntegrityError("order intent has no journaled decision")
                decision_payload = loads(str(decision_row["payload_json"]))
                if canonical_json(decision_payload["decision"]["plan"]) != plan_json or str(
                    decision_row["configuration_hash"]
                ) != str(row["configuration_hash"]):
                    raise JournalIntegrityError(
                        "order intent does not match its journaled decision"
                    )

            previous_hash = ZERO_HASH
            for row in connection.execute("SELECT * FROM journal_entries ORDER BY sequence"):
                payload_json = str(row["payload_json"])
                payload_hash = _hash_text(payload_json)
                if payload_hash != str(row["payload_hash"]):
                    raise JournalIntegrityError("journal payload hash does not match")
                if canonical_json(loads(payload_json)) != payload_json:
                    raise JournalIntegrityError("journal payload JSON is not canonical")
                if str(row["previous_hash"]) != previous_hash:
                    raise JournalIntegrityError("journal hash chain is discontinuous")
                occurred_at = _parse_utc(str(row["occurred_at"]), "occurred_at")
                descriptor = {
                    "configuration_hash": (
                        None
                        if row["configuration_hash"] is None
                        else str(row["configuration_hash"])
                    ),
                    "decision_id": (
                        None if row["decision_id"] is None else str(row["decision_id"])
                    ),
                    "event_id": None if row["event_id"] is None else str(row["event_id"]),
                    "idempotency_key": (
                        None if row["idempotency_key"] is None else str(row["idempotency_key"])
                    ),
                    "kind": JournalEntryKind(str(row["entry_type"])),
                    "occurred_at": occurred_at,
                    "payload_hash": payload_hash,
                    "software_version": str(row["software_version"]),
                }
                if row["idempotency_key"] is not None:
                    intent = connection.execute(
                        """
                        SELECT event_id, decision_id, configuration_hash
                        FROM order_intents
                        WHERE idempotency_key = ?
                        """,
                        (row["idempotency_key"],),
                    ).fetchone()
                    if intent is None or (
                        row["event_id"] != intent["event_id"]
                        or row["decision_id"] != intent["decision_id"]
                        or row["configuration_hash"] != intent["configuration_hash"]
                    ):
                        raise JournalIntegrityError(
                            "journal entry does not match its reserved intent"
                        )
                expected_id = sha256_canonical(descriptor)
                if str(row["entry_id"]) != expected_id:
                    raise JournalIntegrityError("journal entry ID does not match")
                expected_hash = sha256_canonical(
                    {
                        "descriptor": descriptor,
                        "entry_id": expected_id,
                        "previous_hash": previous_hash,
                    }
                )
                if str(row["entry_hash"]) != expected_hash:
                    raise JournalIntegrityError("journal entry hash does not match")
                previous_hash = expected_hash
        except JournalError:
            self._healthy = False
            raise
        except (DatabaseError, KeyError, TypeError, ValueError) as exc:
            self._healthy = False
            raise JournalIntegrityError("journal integrity could not be proven") from exc
