"""Submit one demo order only after durable, append-only intent reservation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from catalyst.domain.enums import AccountMode
from catalyst.domain.models import TradePlan
from catalyst.ports.broker import BrokerPort
from catalyst.ports.journal import JournalPort, OrderIntentState


@dataclass(frozen=True, slots=True)
class DurableSubmissionResult:
    accepted: bool
    code: str
    message: str
    broker_order_id: str | None
    requires_reconciliation: bool

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("submission result code and message must not be empty")
        if self.accepted and not self.broker_order_id:
            raise ValueError("accepted submissions require a broker_order_id")


class DurableDemoExecutor:
    """Fail closed around the broker call; never retry an existing intent."""

    def __init__(self, journal: JournalPort) -> None:
        self.journal = journal

    def submit_once(
        self,
        plan: TradePlan,
        broker: BrokerPort,
        *,
        occurred_at: datetime,
    ) -> DurableSubmissionResult:
        if not self.journal.healthy:
            raise RuntimeError("journal is not healthy; demo execution stays disarmed")
        reserved = self.journal.reserve_order_intent(plan, occurred_at)
        if not reserved:
            return DurableSubmissionResult(
                accepted=False,
                code="DUPLICATE_ORDER_INTENT",
                message="durable idempotency key already exists; broker was not called",
                broker_order_id=None,
                requires_reconciliation=self.journal.order_intent_requires_reconciliation(
                    plan.decision_id
                ),
            )

        try:
            account = broker.account_snapshot()
        except Exception as exc:
            self.journal.record_order_state(
                idempotency_key=plan.decision_id,
                event_id=plan.event_id,
                decision_id=plan.decision_id,
                state=OrderIntentState.REJECTED,
                occurred_at=occurred_at,
                details={
                    "code": "ACCOUNT_CHECK_FAILED",
                    "exception_type": type(exc).__name__,
                },
            )
            raise
        if account.mode is not AccountMode.DEMO:
            self.journal.record_order_state(
                idempotency_key=plan.decision_id,
                event_id=plan.event_id,
                decision_id=plan.decision_id,
                state=OrderIntentState.REJECTED,
                occurred_at=occurred_at,
                details={"code": "DEMO_ONLY", "mode": account.mode},
            )
            return DurableSubmissionResult(
                accepted=False,
                code="DEMO_ONLY",
                message="account was not positively identified as demo; broker was not called",
                broker_order_id=None,
                requires_reconciliation=False,
            )
        if not account.connected:
            self.journal.record_order_state(
                idempotency_key=plan.decision_id,
                event_id=plan.event_id,
                decision_id=plan.decision_id,
                state=OrderIntentState.REJECTED,
                occurred_at=occurred_at,
                details={"code": "BROKER_DISCONNECTED"},
            )
            return DurableSubmissionResult(
                accepted=False,
                code="BROKER_DISCONNECTED",
                message="broker account is disconnected; order submission was not attempted",
                broker_order_id=None,
                requires_reconciliation=False,
            )

        self.journal.record_order_state(
            idempotency_key=plan.decision_id,
            event_id=plan.event_id,
            decision_id=plan.decision_id,
            state=OrderIntentState.SUBMITTING,
            occurred_at=occurred_at,
            details={"code": "SUBMISSION_STARTED"},
        )
        try:
            receipt = broker.submit_bracket(plan)
        except TimeoutError:
            self.journal.record_order_state(
                idempotency_key=plan.decision_id,
                event_id=plan.event_id,
                decision_id=plan.decision_id,
                state=OrderIntentState.UNCERTAIN,
                occurred_at=occurred_at,
                details={"code": "ORDER_TIMEOUT", "exception_type": "TimeoutError"},
            )
            return DurableSubmissionResult(
                accepted=False,
                code="ORDER_TIMEOUT",
                message="broker outcome is uncertain; reconciliation is required",
                broker_order_id=None,
                requires_reconciliation=True,
            )
        except Exception as exc:
            self.journal.record_order_state(
                idempotency_key=plan.decision_id,
                event_id=plan.event_id,
                decision_id=plan.decision_id,
                state=OrderIntentState.UNCERTAIN,
                occurred_at=occurred_at,
                details={"code": "BROKER_EXCEPTION", "exception_type": type(exc).__name__},
            )
            raise

        state = OrderIntentState.ACKNOWLEDGED if receipt.accepted else OrderIntentState.REJECTED
        self.journal.record_order_state(
            idempotency_key=plan.decision_id,
            event_id=plan.event_id,
            decision_id=plan.decision_id,
            state=state,
            occurred_at=occurred_at,
            details={
                "accepted": receipt.accepted,
                "broker_order_id": receipt.broker_order_id,
                "code": receipt.code,
                "message": receipt.message,
            },
        )
        return DurableSubmissionResult(
            accepted=receipt.accepted,
            code=receipt.code,
            message=receipt.message,
            broker_order_id=receipt.broker_order_id,
            requires_reconciliation=False,
        )
