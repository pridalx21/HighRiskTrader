from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from unittest import TestCase

from catalyst.domain.enums import ReasonCode, SystemState
from catalyst.engine.state_machine import EventStateMachine
from catalyst.strategy.event_reaction_retest import EventReactionRetestStrategy
from tests.fixtures import EVENT_TIME, READY_TIME, event, long_market


class EventStateMachineTests(TestCase):
    def setUp(self) -> None:
        self.machine = EventStateMachine()
        self.strategy = EventReactionRetestStrategy()

    def setup_at(self, now):
        return self.strategy.evaluate(event(), long_market(), now)

    def test_sleeping_before_arm_window(self) -> None:
        now = EVENT_TIME - timedelta(minutes=31)
        self.assertEqual(
            self.machine.state_for(now, event(), self.setup_at(now)).state,
            SystemState.SLEEPING,
        )

    def test_armed_before_event(self) -> None:
        now = EVENT_TIME - timedelta(minutes=5)
        self.assertEqual(
            self.machine.state_for(now, event(), self.setup_at(now)).state,
            SystemState.ARMED,
        )

    def test_shock_window_after_release(self) -> None:
        now = EVENT_TIME + timedelta(seconds=45)
        self.assertEqual(
            self.machine.state_for(now, event(), self.setup_at(now)).state,
            SystemState.SHOCK_WINDOW,
        )

    def test_waiting_when_gate_is_red(self) -> None:
        market = replace(long_market(), retest_holds=False)
        setup = self.strategy.evaluate(event(), market, READY_TIME)
        self.assertEqual(
            self.machine.state_for(READY_TIME, event(), setup).state,
            SystemState.WAITING_RETEST,
        )

    def test_ready_when_all_gates_are_green(self) -> None:
        self.assertEqual(
            self.machine.state_for(READY_TIME, event(), self.setup_at(READY_TIME)).state,
            SystemState.READY,
        )

    def test_expired_after_deadline(self) -> None:
        now = EVENT_TIME + timedelta(minutes=16)
        self.assertEqual(
            self.machine.state_for(now, event(), self.setup_at(now)).state,
            SystemState.EXPIRED,
        )

    def test_risk_lock_has_priority(self) -> None:
        self.assertEqual(
            self.machine.state_for(
                READY_TIME,
                event(),
                self.setup_at(READY_TIME),
                risk_locked=True,
            ).state,
            SystemState.LOCKED,
        )

    def test_manual_disarm_has_priority(self) -> None:
        self.assertEqual(
            self.machine.state_for(
                READY_TIME,
                event(),
                self.setup_at(READY_TIME),
                auto_demo_armed=False,
            ).state,
            SystemState.DISARMED,
        )

    def test_bad_stop_produces_waiting_state(self) -> None:
        market = replace(long_market(), stop_candidate=Decimal("102"))
        setup = self.strategy.evaluate(event(), market, READY_TIME)
        self.assertEqual(
            self.machine.state_for(READY_TIME, event(), setup).state,
            SystemState.WAITING_RETEST,
        )

    def test_every_state_result_has_a_stable_code(self) -> None:
        green = self.setup_at(READY_TIME)
        red = self.strategy.evaluate(
            event(),
            replace(long_market(), retest_holds=False),
            READY_TIME,
        )
        cases = (
            (
                self.machine.state_for(
                    EVENT_TIME - timedelta(minutes=31),
                    event(),
                    self.setup_at(EVENT_TIME - timedelta(minutes=31)),
                ),
                ReasonCode.STATE_SLEEPING,
            ),
            (
                self.machine.state_for(
                    EVENT_TIME - timedelta(minutes=5),
                    event(),
                    self.setup_at(EVENT_TIME - timedelta(minutes=5)),
                ),
                ReasonCode.STATE_ARMED,
            ),
            (
                self.machine.state_for(
                    EVENT_TIME + timedelta(seconds=45),
                    event(),
                    self.setup_at(EVENT_TIME + timedelta(seconds=45)),
                ),
                ReasonCode.STATE_SHOCK_WINDOW,
            ),
            (
                self.machine.state_for(READY_TIME, event(), red),
                ReasonCode.STATE_WAITING_RETEST,
            ),
            (
                self.machine.state_for(READY_TIME, event(), green),
                ReasonCode.STATE_READY,
            ),
            (
                self.machine.state_for(
                    EVENT_TIME + timedelta(minutes=16),
                    event(),
                    self.setup_at(EVENT_TIME + timedelta(minutes=16)),
                ),
                ReasonCode.STATE_EXPIRED,
            ),
            (
                self.machine.state_for(
                    READY_TIME,
                    event(),
                    green,
                    risk_locked=True,
                ),
                ReasonCode.STATE_RISK_LOCKED,
            ),
            (
                self.machine.state_for(
                    READY_TIME,
                    event(),
                    green,
                    has_position=True,
                ),
                ReasonCode.STATE_IN_POSITION,
            ),
            (
                self.machine.state_for(
                    READY_TIME,
                    event(),
                    green,
                    auto_demo_armed=False,
                ),
                ReasonCode.STATE_DISARMED,
            ),
        )
        for result, expected_code in cases:
            with self.subTest(code=expected_code):
                self.assertEqual(result.code, expected_code)
                self.assertTrue(result.reason)
