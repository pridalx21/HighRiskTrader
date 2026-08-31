"""Crash/restart tests for durable submission and broker-neutral reconciliation."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from catalyst.adapters.fake_broker import FakeDemoBroker
from catalyst.adapters.sqlite_journal import SQLiteJournal
from catalyst.domain.enums import AccountMode
from catalyst.domain.models import AccountSnapshot, BrokerContract, TradePlan
from catalyst.engine.durable_execution import DurableDemoExecutor
from catalyst.engine.pipeline import DecisionPipeline
from catalyst.engine.reconciliation import RestartReconciler
from catalyst.ports.broker import OrderReceipt
from catalyst.ports.event_feed import SourceEventRecord
from catalyst.ports.journal import OrderIntentState
from catalyst.ports.reconciliation import BrokerOrderLookup, BrokerOrderState
from tests.fixtures import READY_TIME, broker_contract, demo_account, event, long_market


def source_record() -> SourceEventRecord:
    normalized = event()
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


def trade_decision():
    return DecisionPipeline().evaluate(
        event(),
        long_market(),
        demo_account(),
        READY_TIME,
        contract=broker_contract(),
        auto_demo_armed=True,
    )


class CountingBroker:
    def __init__(
        self,
        *,
        timeout: bool = False,
        failure: Exception | None = None,
        reject: bool = False,
        account: AccountSnapshot | None = None,
        account_failure: Exception | None = None,
    ) -> None:
        self.fake = FakeDemoBroker(demo_account(), (broker_contract(),))
        self.timeout = timeout
        self.failure = failure
        self.reject = reject
        self.account = account
        self.account_failure = account_failure
        self.account_calls = 0
        self.submit_calls = 0

    def account_snapshot(self) -> AccountSnapshot:
        self.account_calls += 1
        if self.account_failure is not None:
            raise self.account_failure
        return self.account or self.fake.account_snapshot()

    def contract_for(self, symbol: str) -> BrokerContract:
        return self.fake.contract_for(symbol)

    def submit_bracket(self, plan: TradePlan) -> OrderReceipt:
        self.submit_calls += 1
        if self.timeout:
            raise TimeoutError("synthetic timeout")
        if self.failure is not None:
            raise self.failure
        if self.reject:
            return OrderReceipt(
                False,
                plan.decision_id,
                None,
                "BROKER_REJECT",
                "synthetic demo rejection",
            )
        return self.fake.submit_bracket(plan)


class LookupBroker:
    def __init__(self, lookup: BrokerOrderLookup | Exception) -> None:
        self.lookup = lookup
        self.lookup_calls = 0

    def lookup_order(self, intent):
        self.lookup_calls += 1
        if isinstance(self.lookup, Exception):
            raise self.lookup
        return self.lookup


class DurableRestartIntegrationTests(TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "catalyst.sqlite3"
        self.decision = trade_decision()
        assert self.decision.plan is not None
        self.plan = self.decision.plan

    def tearDown(self) -> None:
        self.directory.cleanup()

    def open(self) -> SQLiteJournal:
        return SQLiteJournal.open(self.path, software_version="restart-test")

    def prepare(self, journal: SQLiteJournal) -> None:
        journal.record_event(source_record())
        journal.record_decision(
            event_id=self.plan.event_id,
            decision_id=self.plan.decision_id,
            decision=self.decision,
            occurred_at=READY_TIME,
        )

    def test_acknowledged_intent_is_never_resubmitted_after_restart(self) -> None:
        first_broker = CountingBroker()
        with self.open() as journal:
            self.prepare(journal)
            result = DurableDemoExecutor(journal).submit_once(
                self.plan,
                first_broker,
                occurred_at=READY_TIME,
            )
            self.assertTrue(result.accepted)
            self.assertEqual(first_broker.submit_calls, 1)

        second_broker = CountingBroker()
        with self.open() as journal:
            duplicate = DurableDemoExecutor(journal).submit_once(
                self.plan,
                second_broker,
                occurred_at=READY_TIME + timedelta(seconds=1),
            )

            self.assertEqual(duplicate.code, "DUPLICATE_ORDER_INTENT")
            self.assertFalse(duplicate.requires_reconciliation)
            self.assertEqual(second_broker.submit_calls, 0)

    def test_crash_after_reservation_never_calls_broker_and_reconciles_found_order(self) -> None:
        with self.open() as journal:
            self.prepare(journal)
            journal.reserve_order_intent(self.plan, READY_TIME)
            journal.record_order_state(
                idempotency_key=self.plan.decision_id,
                event_id=self.plan.event_id,
                decision_id=self.plan.decision_id,
                state=OrderIntentState.SUBMITTING,
                occurred_at=READY_TIME,
                details={"code": "SUBMISSION_STARTED"},
            )

        after_crash_broker = CountingBroker()
        with self.open() as journal:
            duplicate = DurableDemoExecutor(journal).submit_once(
                self.plan,
                after_crash_broker,
                occurred_at=READY_TIME + timedelta(seconds=1),
            )
            self.assertTrue(duplicate.requires_reconciliation)
            self.assertEqual(after_crash_broker.submit_calls, 0)

            lookup = LookupBroker(
                BrokerOrderLookup(
                    BrokerOrderState.FOUND_OPEN,
                    "DEMO-EXISTING-1",
                    "matching demo order found",
                )
            )
            report = RestartReconciler(journal, lookup).reconcile(
                occurred_at=READY_TIME + timedelta(seconds=2)
            )

            self.assertEqual(lookup.lookup_calls, 1)
            self.assertTrue(report.can_request_manual_arm)
            self.assertFalse(report.auto_demo_armed)
            self.assertEqual(report.unresolved_idempotency_keys, ())

    def test_timeout_stays_disarmed_and_not_found_never_resubmits(self) -> None:
        timeout_broker = CountingBroker(timeout=True)
        with self.open() as journal:
            self.prepare(journal)
            timeout = DurableDemoExecutor(journal).submit_once(
                self.plan,
                timeout_broker,
                occurred_at=READY_TIME,
            )
            self.assertEqual(timeout.code, "ORDER_TIMEOUT")
            self.assertTrue(timeout.requires_reconciliation)
            self.assertEqual(timeout_broker.submit_calls, 1)

            duplicate_broker = CountingBroker()
            duplicate = DurableDemoExecutor(journal).submit_once(
                self.plan,
                duplicate_broker,
                occurred_at=READY_TIME + timedelta(seconds=1),
            )
            self.assertEqual(duplicate_broker.submit_calls, 0)
            self.assertTrue(duplicate.requires_reconciliation)

            not_found = LookupBroker(
                BrokerOrderLookup(
                    BrokerOrderState.NOT_FOUND,
                    None,
                    "broker history cannot prove the order outcome",
                )
            )
            report = RestartReconciler(journal, not_found).reconcile(
                occurred_at=READY_TIME + timedelta(seconds=2)
            )

            self.assertFalse(report.can_request_manual_arm)
            self.assertFalse(report.auto_demo_armed)
            self.assertEqual(report.unresolved_idempotency_keys, (self.plan.decision_id,))
            self.assertEqual(timeout_broker.submit_calls, 1)
            self.assertEqual(duplicate_broker.submit_calls, 0)

    def test_reconciliation_adapter_error_is_recorded_as_unknown(self) -> None:
        with self.open() as journal:
            self.prepare(journal)
            journal.reserve_order_intent(self.plan, READY_TIME)
            lookup = LookupBroker(RuntimeError("synthetic read failure"))

            report = RestartReconciler(journal, lookup).reconcile(
                occurred_at=READY_TIME + timedelta(seconds=1)
            )

            self.assertFalse(report.can_request_manual_arm)
            self.assertEqual(report.checked[0].lookup.state, BrokerOrderState.UNKNOWN)
            self.assertIn("RuntimeError", report.checked[0].lookup.reason)
            self.assertEqual(report.unresolved_idempotency_keys, (self.plan.decision_id,))

    def test_non_timeout_broker_exception_is_recorded_then_propagated(self) -> None:
        broker = CountingBroker(failure=RuntimeError("synthetic broker failure"))
        with self.open() as journal:
            self.prepare(journal)
            with self.assertRaisesRegex(RuntimeError, "synthetic broker failure"):
                DurableDemoExecutor(journal).submit_once(
                    self.plan,
                    broker,
                    occurred_at=READY_TIME,
                )
            self.assertEqual(broker.submit_calls, 1)
            self.assertEqual(
                tuple(intent.idempotency_key for intent in journal.unresolved_order_intents()),
                (self.plan.decision_id,),
            )

    def test_explicit_broker_rejection_is_terminal(self) -> None:
        broker = CountingBroker(reject=True)
        with self.open() as journal:
            self.prepare(journal)
            result = DurableDemoExecutor(journal).submit_once(
                self.plan,
                broker,
                occurred_at=READY_TIME,
            )
            self.assertFalse(result.accepted)
            self.assertEqual(result.code, "BROKER_REJECT")
            self.assertFalse(result.requires_reconciliation)
            self.assertEqual(journal.unresolved_order_intents(), ())

    def test_submission_rechecks_demo_mode_and_connection_after_reservation(self) -> None:
        unsafe_accounts = (
            (replace(demo_account(), mode=AccountMode.REAL), "DEMO_ONLY"),
            (replace(demo_account(), mode=AccountMode.UNKNOWN), "DEMO_ONLY"),
            (replace(demo_account(), connected=False), "BROKER_DISCONNECTED"),
        )
        for index, (account, expected_code) in enumerate(unsafe_accounts):
            with self.subTest(mode=account.mode, connected=account.connected):
                path = Path(self.directory.name) / f"unsafe-{index}.sqlite3"
                broker = CountingBroker(account=account)
                with SQLiteJournal.open(path, software_version="restart-test") as journal:
                    self.prepare(journal)
                    result = DurableDemoExecutor(journal).submit_once(
                        self.plan,
                        broker,
                        occurred_at=READY_TIME,
                    )

                    self.assertFalse(result.accepted)
                    self.assertEqual(result.code, expected_code)
                    self.assertFalse(result.requires_reconciliation)
                    self.assertEqual(broker.account_calls, 1)
                    self.assertEqual(broker.submit_calls, 0)
                    self.assertEqual(journal.unresolved_order_intents(), ())

    def test_account_recheck_failure_is_recorded_without_submission(self) -> None:
        broker = CountingBroker(account_failure=RuntimeError("synthetic account failure"))
        with self.open() as journal:
            self.prepare(journal)
            with self.assertRaisesRegex(RuntimeError, "synthetic account failure"):
                DurableDemoExecutor(journal).submit_once(
                    self.plan,
                    broker,
                    occurred_at=READY_TIME,
                )

            self.assertEqual(broker.account_calls, 1)
            self.assertEqual(broker.submit_calls, 0)
            self.assertEqual(journal.unresolved_order_intents(), ())

    def test_unhealthy_journal_blocks_execution_and_reconciliation(self) -> None:
        journal = self.open()
        self.prepare(journal)
        journal.close()
        with self.assertRaisesRegex(RuntimeError, "journal is not healthy"):
            DurableDemoExecutor(journal).submit_once(
                self.plan,
                CountingBroker(),
                occurred_at=READY_TIME,
            )
        lookup = LookupBroker(BrokerOrderLookup(BrokerOrderState.UNKNOWN, None, "not checked"))
        with self.assertRaisesRegex(RuntimeError, "journal is not healthy"):
            RestartReconciler(journal, lookup).reconcile(occurred_at=READY_TIME)

    def test_reconciliation_without_unresolved_intents_stays_disarmed(self) -> None:
        lookup = LookupBroker(BrokerOrderLookup(BrokerOrderState.UNKNOWN, None, "not needed"))
        with self.open() as journal:
            self.prepare(journal)
            report = RestartReconciler(journal, lookup).reconcile(occurred_at=READY_TIME)
            self.assertTrue(report.can_request_manual_arm)
            self.assertFalse(report.auto_demo_armed)
            self.assertEqual(report.checked, ())
            self.assertEqual(lookup.lookup_calls, 0)
