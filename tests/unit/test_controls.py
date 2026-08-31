from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from catalyst.controls import ControlCommand, LocalKillSwitch, OperatorControlPlane

NOW = datetime(2030, 1, 10, 13, 30, tzinfo=UTC)


class FakeExecution:
    def __init__(self) -> None:
        self._armed = False
        self.fail_disarm = False
        self.fail_arm = False

    @property
    def armed(self) -> bool:
        return self._armed

    def arm_demo_execution(self) -> None:
        if self.fail_arm:
            raise RuntimeError("arm failed")
        self._armed = True

    def disarm(self) -> None:
        if self.fail_disarm:
            raise RuntimeError("disarm failed")
        self._armed = False


class FakeAudit:
    def __init__(self) -> None:
        self.healthy = True
        self.fail_write = False
        self.records: list[dict[str, Any]] = []

    def record_heartbeat(
        self,
        *,
        component: str,
        status: str,
        occurred_at: datetime,
        details: dict[str, Any] | None = None,
    ) -> bool:
        if self.fail_write:
            raise RuntimeError("journal unavailable")
        self.records.append(
            {
                "component": component,
                "status": status,
                "occurred_at": occurred_at,
                "details": details,
            }
        )
        return True


class OperatorControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.execution = FakeExecution()
        self.audit = FakeAudit()
        self.kill = LocalKillSwitch(Path(self.temp.name) / "kill.json")
        self.token = "local-test-token"
        self.controls = OperatorControlPlane(
            execution=self.execution,
            audit=self.audit,
            kill_switch=self.kill,
            authentication_digest=OperatorControlPlane.digest_token(self.token),
        )

    def test_arm_requires_auth_confirmation_fresh_data_and_audit(self) -> None:
        wrong = self.controls.execute(
            ControlCommand.ARM_AUTO_DEMO,
            token="wrong",
            confirmed=True,
            occurred_at=NOW,
            dashboard_source_at=NOW,
        )
        self.assertEqual(wrong.code, "AUTH_FAILED")
        not_confirmed = self.controls.execute(
            ControlCommand.ARM_AUTO_DEMO,
            token=self.token,
            confirmed=False,
            occurred_at=NOW,
            dashboard_source_at=NOW,
        )
        self.assertEqual(not_confirmed.code, "CONFIRMATION_REQUIRED")
        stale = self.controls.execute(
            ControlCommand.ARM_AUTO_DEMO,
            token=self.token,
            confirmed=True,
            occurred_at=NOW,
            dashboard_source_at=NOW - timedelta(seconds=10),
        )
        self.assertEqual(stale.code, "DASHBOARD_STALE")
        future = self.controls.execute(
            ControlCommand.ARM_AUTO_DEMO,
            token=self.token,
            confirmed=True,
            occurred_at=NOW,
            dashboard_source_at=NOW + timedelta(seconds=1),
        )
        self.assertEqual(future.code, "CLOCK_INVALID")
        self.audit.healthy = False
        unhealthy = self.controls.execute(
            ControlCommand.ARM_AUTO_DEMO,
            token=self.token,
            confirmed=True,
            occurred_at=NOW,
            dashboard_source_at=NOW,
        )
        self.assertEqual(unhealthy.code, "JOURNAL_UNHEALTHY")

    def test_arm_and_disarm_are_audited(self) -> None:
        armed = self.controls.execute(
            ControlCommand.ARM_AUTO_DEMO,
            token=self.token,
            confirmed=True,
            occurred_at=NOW,
            dashboard_source_at=NOW,
        )
        self.assertTrue(armed.accepted)
        self.assertTrue(armed.journaled)
        self.assertTrue(self.execution.armed)
        disarmed = self.controls.execute(
            ControlCommand.DISARM_AUTO_DEMO,
            token=self.token,
            confirmed=True,
            occurred_at=NOW + timedelta(seconds=1),
            dashboard_source_at=NOW,
        )
        self.assertEqual(disarmed.code, "AUTO_DEMO_DISARMED")
        self.assertFalse(self.execution.armed)
        self.assertGreaterEqual(len(self.audit.records), 2)

    def test_arm_rolls_back_when_audit_write_fails(self) -> None:
        self.audit.fail_write = True
        result = self.controls.execute(
            ControlCommand.ARM_AUTO_DEMO,
            token=self.token,
            confirmed=True,
            occurred_at=NOW,
            dashboard_source_at=NOW,
        )
        self.assertEqual(result.code, "AUDIT_FAILED")
        self.assertFalse(self.execution.armed)

    def test_kill_switch_latches_even_when_dependencies_fail(self) -> None:
        self.execution._armed = True
        self.execution.fail_disarm = True
        self.audit.healthy = False
        result = self.controls.execute(
            ControlCommand.KILL_SWITCH,
            token=self.token,
            confirmed=True,
            occurred_at=NOW,
            reason="simulated dependency failure",
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "KILL_SWITCH_LATCHED")
        self.assertTrue(self.kill.active)
        blocked = self.controls.execute(
            ControlCommand.ARM_AUTO_DEMO,
            token=self.token,
            confirmed=True,
            occurred_at=NOW + timedelta(seconds=1),
            dashboard_source_at=NOW + timedelta(seconds=1),
        )
        self.assertEqual(blocked.code, "KILL_SWITCH_ACTIVE")

    def test_incident_clear_requires_disarm_and_healthy_audit(self) -> None:
        self.kill.engage(occurred_at=NOW, reason="test")
        self.execution._armed = True
        armed = self.controls.execute(
            ControlCommand.ACKNOWLEDGE_INCIDENT,
            token=self.token,
            confirmed=True,
            occurred_at=NOW + timedelta(seconds=1),
        )
        self.assertEqual(armed.code, "DISARM_REQUIRED")
        self.execution._armed = False
        self.audit.healthy = False
        unhealthy = self.controls.execute(
            ControlCommand.ACKNOWLEDGE_INCIDENT,
            token=self.token,
            confirmed=True,
            occurred_at=NOW + timedelta(seconds=2),
        )
        self.assertEqual(unhealthy.code, "JOURNAL_UNHEALTHY")
        self.audit.healthy = True
        cleared = self.controls.execute(
            ControlCommand.ACKNOWLEDGE_INCIDENT,
            token=self.token,
            confirmed=True,
            occurred_at=NOW + timedelta(seconds=3),
        )
        self.assertTrue(cleared.accepted)
        self.assertFalse(self.kill.active)

    def test_incident_clear_rolls_back_if_audit_fails(self) -> None:
        self.kill.engage(occurred_at=NOW, reason="test")
        self.audit.fail_write = True
        result = self.controls.execute(
            ControlCommand.ACKNOWLEDGE_INCIDENT,
            token=self.token,
            confirmed=True,
            occurred_at=NOW + timedelta(seconds=1),
        )
        self.assertEqual(result.code, "AUDIT_FAILED")
        self.assertTrue(self.kill.active)

    def test_target_failures_are_fail_closed(self) -> None:
        self.execution.fail_arm = True
        arm = self.controls.execute(
            ControlCommand.ARM_AUTO_DEMO,
            token=self.token,
            confirmed=True,
            occurred_at=NOW,
            dashboard_source_at=NOW,
        )
        self.assertEqual(arm.code, "ARM_FAILED")
        self.execution.fail_disarm = True
        disarm = self.controls.execute(
            ControlCommand.DISARM_AUTO_DEMO,
            token=self.token,
            confirmed=True,
            occurred_at=NOW + timedelta(seconds=1),
        )
        self.assertEqual(disarm.code, "DISARM_FAILED")

    def test_invalid_configuration_and_time_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            OperatorControlPlane(
                execution=self.execution,
                audit=self.audit,
                kill_switch=self.kill,
                authentication_digest="short",
            )
        with self.assertRaises(ValueError):
            OperatorControlPlane.digest_token("")
        with self.assertRaises(ValueError):
            self.kill.engage(occurred_at=NOW, reason="")
        with self.assertRaises(ValueError):
            self.controls.execute(
                ControlCommand.DISARM_AUTO_DEMO,
                token=self.token,
                confirmed=True,
                occurred_at=datetime(2030, 1, 1),
            )


if __name__ == "__main__":
    unittest.main()
