"""One shared decision pipeline for replay and demo modes."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256

from catalyst.config import RuntimeConfig
from catalyst.domain.enums import Direction, ReasonCode, SystemState
from catalyst.domain.models import (
    AccountSnapshot,
    BrokerContract,
    EconomicEvent,
    MarketSnapshot,
    PipelineDecision,
    RiskDecision,
    TradePlan,
)
from catalyst.engine.state_machine import EventStateMachine
from catalyst.risk.manager import RiskManager
from catalyst.strategy.event_reaction_retest import EventReactionRetestStrategy

SETUP_SEQUENCE = 1


class DecisionPipeline:
    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig()
        self.strategy = EventReactionRetestStrategy(self.config.strategy)
        self.risk_manager = RiskManager(self.config.risk.policy)
        self.state_machine = EventStateMachine(self.config.state_machine)

    def evaluate(
        self,
        event: EconomicEvent,
        market: MarketSnapshot,
        account: AccountSnapshot,
        now: datetime,
        *,
        contract: BrokerContract,
        auto_demo_armed: bool | None = None,
    ) -> PipelineDecision:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware UTC")
        if now.utcoffset() != timedelta(0):
            raise ValueError("now must be normalized to UTC")
        armed = self.config.system.auto_demo_armed if auto_demo_armed is None else auto_demo_armed
        setup = self.strategy.evaluate(event, market, now)
        preliminary_risk = self.risk_manager.assess(
            account,
            now,
            self.config.strategy.maximum_data_age_seconds,
        )
        risk_locked = not preliminary_risk.allowed
        state_result = self.state_machine.state_for(
            now,
            event,
            setup,
            auto_demo_armed=armed,
            risk_locked=risk_locked,
        )

        if state_result.state is not SystemState.READY:
            risk = (
                preliminary_risk
                if not preliminary_risk.allowed
                else RiskDecision(
                    False,
                    ReasonCode.SETUP_NOT_READY,
                    "setup is not ready for risk allocation",
                )
            )
            failed_gates = tuple(
                gate
                for gate in (
                    setup.catalyst,
                    setup.acceptance,
                    setup.confirmation,
                    setup.execution,
                )
                if not gate.passed
            )
            if not preliminary_risk.allowed:
                code = preliminary_risk.code
                reason = preliminary_risk.reason
            elif failed_gates:
                code = failed_gates[0].code
                reason = failed_gates[0].reason
            else:
                code = state_result.code
                reason = state_result.reason
            return PipelineDecision(
                state_result.state,
                code,
                setup,
                risk,
                None,
                reason,
                self.config.configuration_hash,
            )

        if setup.direction is None:
            risk = RiskDecision(
                False,
                ReasonCode.NO_DIRECTION,
                "ready setup has no direction",
            )
            return PipelineDecision(
                SystemState.LOCKED,
                risk.code,
                setup,
                risk,
                None,
                risk.reason,
                self.config.configuration_hash,
            )

        entry = market.ask if setup.direction is Direction.LONG else market.bid
        try:
            if contract.symbol != market.symbol:
                raise ValueError("broker contract symbol does not match market symbol")
            if contract.account_currency.upper() != account.currency.upper():
                raise ValueError("broker contract account currency does not match account")
            sizing = self.risk_manager.size_position(
                preliminary_risk.risk_amount,
                entry,
                market.stop_candidate,
                contract,
            )
            plan = TradePlan(
                decision_id=self._decision_id(event, market, setup.direction),
                event_id=event.event_id,
                strategy_id=self.strategy.config.strategy_id,
                symbol=market.symbol,
                direction=setup.direction,
                created_at=now,
                entry=entry,
                stop=market.stop_candidate,
                risk_amount=preliminary_risk.risk_amount,
                maximum_loss=sizing.maximum_loss,
                quantity=sizing.quantity,
                configuration_hash=self.config.configuration_hash,
                rationale=(
                    setup.catalyst.reason,
                    setup.acceptance.reason,
                    setup.confirmation.reason,
                    setup.execution.reason,
                ),
            )
        except ValueError as exc:
            risk = RiskDecision(
                False,
                ReasonCode.PLAN_INVALID,
                f"trade plan is invalid: {exc}",
            )
            return PipelineDecision(
                SystemState.LOCKED,
                risk.code,
                setup,
                risk,
                None,
                risk.reason,
                self.config.configuration_hash,
            )

        return PipelineDecision(
            SystemState.READY,
            ReasonCode.TRADE_PLAN_READY,
            setup,
            preliminary_risk,
            plan,
            "trade plan ready",
            self.config.configuration_hash,
        )

    def _decision_id(
        self,
        event: EconomicEvent,
        market: MarketSnapshot,
        direction: Direction,
    ) -> str:
        source = "|".join(
            (
                event.event_id,
                market.symbol,
                self.strategy.config.strategy_id,
                direction.value,
                str(SETUP_SEQUENCE),
            )
        )
        return sha256(source.encode("utf-8")).hexdigest()[:20]
