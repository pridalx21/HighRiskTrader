"""Read-only one-page operator dashboard presentation model.

Streamlit is imported lazily so core and CI do not depend on the optional UI package.
The dashboard never constructs or mutates numeric trade plans; controls are routed
through :mod:`catalyst.controls`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from importlib import import_module
from typing import Any

from catalyst.controls import ControlCommand, OperatorControlPlane
from catalyst.domain.enums import SystemState


@dataclass(frozen=True, slots=True)
class GateView:
    name: str
    passed: bool
    code: str
    reason: str
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.name, self.code, self.reason)):
            raise ValueError("gate view text fields must not be empty")


@dataclass(frozen=True, slots=True)
class PlanView:
    direction: str
    entry: Decimal
    stop: Decimal
    volume: Decimal
    maximum_planned_loss_chf: Decimal


@dataclass(frozen=True, slots=True)
class AccountView:
    balance_chf: Decimal
    equity_chf: Decimal
    day_pnl_chf: Decimal
    day_pnl_r: Decimal
    open_risk_chf: Decimal
    active_locks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    generated_at: datetime
    source_at: datetime
    next_event: str | None
    affected_markets: tuple[str, ...]
    state: SystemState
    gates: tuple[GateView, ...]
    plan: PlanView | None
    account: AccountView
    orders: tuple[str, ...]
    positions: tuple[str, ...]
    recent_decisions: tuple[str, ...]
    replay_report_name: str | None = None
    replay_report_bytes: bytes | None = None
    maximum_age: timedelta = timedelta(seconds=5)

    def __post_init__(self) -> None:
        _require_utc(self.generated_at, "generated_at")
        _require_utc(self.source_at, "source_at")
        if self.maximum_age <= timedelta(0):
            raise ValueError("maximum_age must be positive")
        if len(self.gates) > 4:
            raise ValueError("dashboard supports at most the four deterministic strategy gates")
        if self.replay_report_bytes is not None and not self.replay_report_name:
            raise ValueError("replay report bytes require a file name")

    def is_stale(self, at: datetime) -> bool:
        _require_utc(at, "at")
        return self.source_at > at or at - self.source_at > self.maximum_age


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be normalized to UTC")


def render_streamlit(
    snapshot: DashboardSnapshot,
    controls: OperatorControlPlane,
    *,
    authentication_token: str,
    now: datetime,
) -> None:
    """Render one safe local page. No numeric trading inputs are exposed."""

    _require_utc(now, "now")
    st: Any = import_module("streamlit")
    stale = snapshot.is_stale(now)

    st.set_page_config(page_title="CATALYST Demo", layout="wide")
    st.title("CATALYST — Demo Operator")
    if stale:
        st.error("STALE DATA — automatic demo execution cannot be armed")
    if controls.kill_switch.active:
        st.error("KILL SWITCH ACTIVE")

    top = st.columns(3)
    top[0].metric("State", snapshot.state.value)
    top[1].metric("Next event", snapshot.next_event or "none")
    top[2].metric("Affected markets", ", ".join(snapshot.affected_markets) or "none")

    st.subheader("Strategy gates")
    for gate in snapshot.gates:
        mark = "PASS" if gate.passed else "FAIL"
        st.write(f"{gate.name}: {mark} — {gate.code} — {gate.reason}")
        if gate.evidence:
            st.caption(" | ".join(gate.evidence))

    st.subheader("Proposed trade")
    if snapshot.plan is None:
        st.write("No executable trade plan")
    else:
        st.write(
            {
                "direction": snapshot.plan.direction,
                "entry": str(snapshot.plan.entry),
                "stop": str(snapshot.plan.stop),
                "volume": str(snapshot.plan.volume),
                "maximum_planned_loss_chf": str(snapshot.plan.maximum_planned_loss_chf),
            }
        )

    st.subheader("Account and risk")
    st.write(
        {
            "balance_chf": str(snapshot.account.balance_chf),
            "equity_chf": str(snapshot.account.equity_chf),
            "day_pnl_chf": str(snapshot.account.day_pnl_chf),
            "day_pnl_r": str(snapshot.account.day_pnl_r),
            "open_risk_chf": str(snapshot.account.open_risk_chf),
            "active_locks": snapshot.account.active_locks,
        }
    )

    left, middle, right = st.columns(3)
    with left:
        st.subheader("Orders")
        for row in snapshot.orders or ("none",):
            st.write(row)
    with middle:
        st.subheader("Positions")
        for row in snapshot.positions or ("none",):
            st.write(row)
    with right:
        st.subheader("Recent decisions")
        for row in snapshot.recent_decisions or ("none",):
            st.write(row)

    if snapshot.replay_report_bytes is not None and snapshot.replay_report_name is not None:
        st.download_button(
            "Download replay report",
            data=snapshot.replay_report_bytes,
            file_name=snapshot.replay_report_name,
            mime="application/json",
        )

    st.subheader("Controls")
    st.caption("Controls are typed. This page has no direction, entry, stop, volume, or risk inputs.")
    confirm = st.checkbox("Confirm next control action")
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("ARM AUTO-DEMO", disabled=stale or controls.kill_switch.active):
        result = controls.execute(
            ControlCommand.ARM_AUTO_DEMO,
            token=authentication_token,
            confirmed=confirm,
            occurred_at=now,
            dashboard_source_at=snapshot.source_at,
        )
        st.write(result.message)
    if c2.button("DISARM"):
        result = controls.execute(
            ControlCommand.DISARM_AUTO_DEMO,
            token=authentication_token,
            confirmed=confirm,
            occurred_at=now,
            dashboard_source_at=snapshot.source_at,
        )
        st.write(result.message)
    if c3.button("KILL SWITCH"):
        result = controls.execute(
            ControlCommand.KILL_SWITCH,
            token=authentication_token,
            confirmed=confirm,
            occurred_at=now,
            dashboard_source_at=snapshot.source_at,
            reason="dashboard kill switch",
        )
        st.write(result.message)
    if c4.button("ACK INCIDENT"):
        result = controls.execute(
            ControlCommand.ACKNOWLEDGE_INCIDENT,
            token=authentication_token,
            confirmed=confirm,
            occurred_at=now,
            dashboard_source_at=snapshot.source_at,
            reason="operator incident review",
        )
        st.write(result.message)
