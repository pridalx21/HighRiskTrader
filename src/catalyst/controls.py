"""Narrow authenticated operator controls for demo-only execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from typing import Any, Protocol

from catalyst.domain.serialization import canonical_json


class ControlCommand(StrEnum):
    ARM_AUTO_DEMO = "arm_auto_demo"
    DISARM_AUTO_DEMO = "disarm_auto_demo"
    KILL_SWITCH = "kill_switch"
    ACKNOWLEDGE_INCIDENT = "acknowledge_incident"


@dataclass(frozen=True, slots=True)
class ControlResult:
    command: ControlCommand
    accepted: bool
    code: str
    message: str
    occurred_at: datetime
    kill_switch_active: bool
    journaled: bool

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("control result code and message must not be empty")
        _require_utc(self.occurred_at, "occurred_at")


class DemoExecutionControl(Protocol):
    @property
    def armed(self) -> bool: ...

    def arm_demo_execution(self) -> None: ...

    def disarm(self) -> None: ...


class ControlAuditPort(Protocol):
    @property
    def healthy(self) -> bool: ...

    def record_heartbeat(
        self,
        *,
        component: str,
        status: str,
        occurred_at: datetime,
        details: Mapping[str, Any] | None = None,
    ) -> bool: ...


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be normalized to UTC")


class LocalKillSwitch:
    """Persistent local safety latch independent of the dashboard process."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def active(self) -> bool:
        return self.path.exists()

    def engage(self, *, occurred_at: datetime, reason: str) -> None:
        _require_utc(occurred_at, "occurred_at")
        if not reason.strip():
            raise ValueError("kill-switch reason must not be empty")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            canonical_json({"engaged_at": occurred_at, "reason": reason}),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class OperatorControlPlane:
    """Authenticate and execute four typed controls without numeric trade input."""

    def __init__(
        self,
        *,
        execution: DemoExecutionControl,
        audit: ControlAuditPort,
        kill_switch: LocalKillSwitch,
        authentication_digest: str,
        maximum_dashboard_age: timedelta = timedelta(seconds=5),
    ) -> None:
        if len(authentication_digest) != 64:
            raise ValueError("authentication_digest must be a SHA-256 hex digest")
        if maximum_dashboard_age <= timedelta(0):
            raise ValueError("maximum_dashboard_age must be positive")
        self.execution = execution
        self.audit = audit
        self.kill_switch = kill_switch
        self.authentication_digest = authentication_digest.lower()
        self.maximum_dashboard_age = maximum_dashboard_age

    @staticmethod
    def digest_token(token: str) -> str:
        if not token:
            raise ValueError("authentication token must not be empty")
        return sha256(token.encode("utf-8")).hexdigest()

    def _authenticated(self, token: str) -> bool:
        if not token:
            return False
        return compare_digest(self.digest_token(token), self.authentication_digest)

    def _audit(
        self,
        *,
        command: ControlCommand,
        status: str,
        occurred_at: datetime,
        details: Mapping[str, Any],
    ) -> bool:
        try:
            if not self.audit.healthy:
                return False
            return self.audit.record_heartbeat(
                component="operator_control",
                status=status,
                occurred_at=occurred_at,
                details={"command": command, **dict(details)},
            )
        except Exception:
            return False

    def execute(
        self,
        command: ControlCommand,
        *,
        token: str,
        confirmed: bool,
        occurred_at: datetime,
        dashboard_source_at: datetime | None = None,
        reason: str = "operator request",
    ) -> ControlResult:
        _require_utc(occurred_at, "occurred_at")
        if dashboard_source_at is not None:
            _require_utc(dashboard_source_at, "dashboard_source_at")
        if not self._authenticated(token):
            return self._result(
                command, False, "AUTH_FAILED", "local control authentication failed", occurred_at
            )
        if not confirmed:
            return self._result(
                command, False, "CONFIRMATION_REQUIRED", "control action was not confirmed", occurred_at
            )

        if command is ControlCommand.KILL_SWITCH:
            self.kill_switch.engage(occurred_at=occurred_at, reason=reason)
            target_error: str | None = None
            try:
                self.execution.disarm()
            except Exception as exc:
                target_error = type(exc).__name__
            journaled = self._audit(
                command=command,
                status="engaged",
                occurred_at=occurred_at,
                details={"reason": reason, "target_error": target_error},
            )
            code = "KILL_SWITCH_ENGAGED" if target_error is None else "KILL_SWITCH_LATCHED"
            message = (
                "kill switch engaged and demo execution disarmed"
                if target_error is None
                else "kill switch latched locally; execution target could not be reached"
            )
            return ControlResult(command, True, code, message, occurred_at, True, journaled)

        if command is ControlCommand.DISARM_AUTO_DEMO:
            try:
                self.execution.disarm()
            except Exception as exc:
                return self._result(
                    command,
                    False,
                    "DISARM_FAILED",
                    f"demo execution disarm failed with {type(exc).__name__}",
                    occurred_at,
                )
            journaled = self._audit(
                command=command,
                status="disarmed",
                occurred_at=occurred_at,
                details={},
            )
            return ControlResult(
                command,
                True,
                "AUTO_DEMO_DISARMED",
                "automatic demo execution is disarmed",
                occurred_at,
                self.kill_switch.active,
                journaled,
            )

        if command is ControlCommand.ACKNOWLEDGE_INCIDENT:
            if self.execution.armed:
                return self._result(
                    command,
                    False,
                    "DISARM_REQUIRED",
                    "incident cannot be cleared while demo execution is armed",
                    occurred_at,
                )
            if not self.audit.healthy:
                return self._result(
                    command,
                    False,
                    "JOURNAL_UNHEALTHY",
                    "incident cannot be cleared without a healthy audit journal",
                    occurred_at,
                )
            self.kill_switch.clear()
            journaled = self._audit(
                command=command,
                status="acknowledged",
                occurred_at=occurred_at,
                details={"reason": reason},
            )
            if not journaled:
                self.kill_switch.engage(occurred_at=occurred_at, reason="audit failure during clear")
                return self._result(
                    command,
                    False,
                    "AUDIT_FAILED",
                    "incident clear was rolled back because audit persistence failed",
                    occurred_at,
                )
            return ControlResult(
                command,
                True,
                "INCIDENT_ACKNOWLEDGED",
                "incident acknowledged; kill switch cleared while execution remains disarmed",
                occurred_at,
                False,
                True,
            )

        if command is ControlCommand.ARM_AUTO_DEMO:
            if self.kill_switch.active:
                return self._result(
                    command,
                    False,
                    "KILL_SWITCH_ACTIVE",
                    "automatic demo execution cannot arm while the kill switch is active",
                    occurred_at,
                )
            if not self.audit.healthy:
                return self._result(
                    command,
                    False,
                    "JOURNAL_UNHEALTHY",
                    "automatic demo execution cannot arm without a healthy audit journal",
                    occurred_at,
                )
            if dashboard_source_at is None or occurred_at - dashboard_source_at > self.maximum_dashboard_age:
                return self._result(
                    command,
                    False,
                    "DASHBOARD_STALE",
                    "automatic demo execution cannot arm from stale or missing dashboard state",
                    occurred_at,
                )
            if dashboard_source_at > occurred_at:
                return self._result(
                    command,
                    False,
                    "CLOCK_INVALID",
                    "dashboard source timestamp is in the future",
                    occurred_at,
                )
            try:
                self.execution.arm_demo_execution()
            except Exception as exc:
                return self._result(
                    command,
                    False,
                    "ARM_FAILED",
                    f"demo execution arm failed with {type(exc).__name__}",
                    occurred_at,
                )
            journaled = self._audit(
                command=command,
                status="armed",
                occurred_at=occurred_at,
                details={"dashboard_source_at": dashboard_source_at},
            )
            if not journaled:
                self.execution.disarm()
                return self._result(
                    command,
                    False,
                    "AUDIT_FAILED",
                    "arming was rolled back because the control audit could not be persisted",
                    occurred_at,
                )
            return ControlResult(
                command,
                True,
                "AUTO_DEMO_ARMED",
                "automatic demo execution armed for this process",
                occurred_at,
                False,
                True,
            )

        raise ValueError(f"unsupported control command: {command}")

    def _result(
        self,
        command: ControlCommand,
        accepted: bool,
        code: str,
        message: str,
        occurred_at: datetime,
    ) -> ControlResult:
        journaled = self._audit(
            command=command,
            status="accepted" if accepted else "rejected",
            occurred_at=occurred_at,
            details={"code": code},
        )
        return ControlResult(
            command,
            accepted,
            code,
            message,
            occurred_at,
            self.kill_switch.active,
            journaled,
        )
