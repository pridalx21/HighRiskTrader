from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from catalyst.adapters.guarded_demo_broker import GuardedDemoBroker
from catalyst.controls import LocalKillSwitch
from catalyst.domain.enums import AccountMode, EventImportance, EventStatus
from catalyst.domain.models import AccountSnapshot, BrokerContract, EconomicEvent
from catalyst.ports.broker import OrderReceipt
from catalyst.ports.reconciliation import BrokerOrderLookup, BrokerOrderState
from catalyst.replay.models import CrossAssetRule, RawBar, RawTick
from catalyst.runtime import CatalystRuntime, LivePrimaryRules, LiveRuntimeConfig, load_live_runtime_config


NOW = datetime(2030, 1, 10, 13, 32, 10, tzinfo=UTC)
EVENT_AT = datetime(2030, 1, 10, 13, 30, tzinfo=UTC)


def event() -> EconomicEvent:
    return EconomicEvent(
        event_id="LIVE_EVENT_001",
        name="Synthetic live event",
        scheduled_at=EVENT_AT,
        ingested_at=EVENT_AT - timedelta(days=1),
        currency="USD",
        importance=EventImportance.HIGH,
        status=EventStatus.SCHEDULED,
        eligible_symbols=("PRIMARY",),
        source="manual_csv",
    )


def account() -> AccountSnapshot:
    return AccountSnapshot(
        mode=AccountMode.DEMO,
        currency="CHF",
        balance=Decimal("1000"),
        equity=Decimal("1000"),
        day_start_equity=Decimal("1000"),
        month_start_equity=Decimal("1000"),
        daily_realized_pnl=Decimal("0"),
        consecutive_losses=0,
        active_risk_clusters=0,
        open_worst_case_risk=Decimal("0"),
        timestamp=NOW,
        connected=True,
    )


def contract() -> BrokerContract:
    return BrokerContract(
        symbol="PRIMARY",
        tick_size=Decimal("0.1"),
        tick_value=Decimal("1"),
        contract_size=Decimal("1"),
        profit_currency="CHF",
        account_currency="CHF",
        profit_to_account_rate=Decimal("1"),
        volume_minimum=Decimal("0.1"),
        volume_maximum=Decimal("100"),
        volume_step=Decimal("0.1"),
        commission_per_volume=Decimal("0.01"),
        slippage_ticks=Decimal("1"),
    )


class FakeJournal:
    healthy = True

    def __init__(self) -> None:
        self.decisions = []
        self.heartbeats = []

    def record_decision(self, **kwargs):
        self.decisions.append(kwargs)
        return True

    def record_heartbeat(self, **kwargs):
        self.heartbeats.append(kwargs)
        return True

    def reserve_order_intent(self, plan, occurred_at):
        return True

    def order_intent_requires_reconciliation(self, idempotency_key):
        return False


class FakeDelegate:
    def __init__(self) -> None:
        self._armed = False
        self.disarms = 0
        self.submissions = 0

    @property
    def armed(self):
        return self._armed

    def arm_demo_execution(self):
        self._armed = True

    def disarm(self):
        self.disarms += 1
        self._armed = False

    def account_snapshot(self):
        return account()

    def contract_for(self, symbol):
        if symbol != "PRIMARY":
            raise RuntimeError("unknown symbol")
        return contract()

    def submit_bracket(self, plan):
        self.submissions += 1
        return OrderReceipt(True, plan.decision_id, "B1", "ACCEPTED", "accepted")

    def lookup_order(self, intent):
        return BrokerOrderLookup(BrokerOrderState.NOT_FOUND, None, "not found")


class FakeMarketData:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.ticks = {
            "PRIMARY": (
                RawTick("PRIMARY", EVENT_AT - timedelta(minutes=30), Decimal("99.8"), Decimal("100.0"), 1),
                RawTick("PRIMARY", EVENT_AT - timedelta(minutes=20), Decimal("95.0"), Decimal("95.2"), 2),
                RawTick("PRIMARY", EVENT_AT - timedelta(minutes=10), Decimal("97.9"), Decimal("98.1"), 3),
                RawTick("PRIMARY", EVENT_AT + timedelta(seconds=90), Decimal("100.2"), Decimal("100.4"), 4),
                RawTick("PRIMARY", EVENT_AT + timedelta(minutes=2), Decimal("100.0"), Decimal("100.2"), 5),
                RawTick("PRIMARY", NOW - timedelta(seconds=1), Decimal("101.2"), Decimal("101.4"), 6),
            ),
            "R1": (
                RawTick("R1", EVENT_AT - timedelta(minutes=10), Decimal("49.9"), Decimal("50.1"), 1),
                RawTick("R1", NOW - timedelta(seconds=1), Decimal("50.9"), Decimal("51.1"), 2),
            ),
            "R2": (
                RawTick("R2", EVENT_AT - timedelta(minutes=10), Decimal("69.9"), Decimal("70.1"), 1),
                RawTick("R2", NOW - timedelta(seconds=1), Decimal("70.9"), Decimal("71.1"), 2),
            ),
        }
        self.bar = RawBar(
            symbol="PRIMARY",
            opened_at=EVENT_AT - timedelta(minutes=30),
            closed_at=EVENT_AT,
            bid_open=Decimal("99.0"),
            bid_high=Decimal("99.8"),
            bid_low=Decimal("95.0"),
            bid_close=Decimal("97.9"),
            ask_open=Decimal("99.2"),
            ask_high=Decimal("100.0"),
            ask_low=Decimal("95.2"),
            ask_close=Decimal("98.1"),
            source_sequence=1,
        )

    def ticks_between(self, symbol, start, end):
        if self.fail:
            raise RuntimeError("market data unavailable")
        return tuple(tick for tick in self.ticks[symbol] if start <= tick.timestamp <= end)

    def latest_tick(self, symbol, *, at, maximum_age):
        tick = self.ticks[symbol][-1]
        if at - tick.timestamp > maximum_age:
            raise RuntimeError("stale")
        return tick

    def bars_between(self, symbol, start, end, *, timeframe_seconds):
        return (self.bar,)


def live_config() -> LiveRuntimeConfig:
    return LiveRuntimeConfig(
        primaries={
            "PRIMARY": LivePrimaryRules(
                (
                    CrossAssetRule("R1", 1, Decimal("0.5")),
                    CrossAssetRule("R2", 1, Decimal("0.5")),
                )
            )
        }
    )


class RuntimeTests(TestCase):
    def test_live_config_loader_is_strict(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "live.json"
            path.write_text(
                '{"poll_seconds":"1","bar_seconds":60,"session_cutoff_minutes":120,'
                '"primaries":{"PRIMARY":{"related":['
                '{"symbol":"R1","polarity":1,"minimum_move":"0.5"}]}}}',
                encoding="utf-8",
            )
            loaded = load_live_runtime_config(path)
            self.assertEqual(loaded.poll_seconds, Decimal("1"))
            self.assertEqual(loaded.primaries["PRIMARY"].related[0].symbol, "R1")

            path.write_text('{"poll_seconds":1}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_live_runtime_config(path)

    def test_shadow_cycle_builds_same_pipeline_plan_without_submitting(self) -> None:
        with TemporaryDirectory() as directory:
            delegate = FakeDelegate()
            broker = GuardedDemoBroker(
                delegate,
                LocalKillSwitch(Path(directory) / "kill.json"),
            )
            journal = FakeJournal()
            runtime = CatalystRuntime(
                config=__import__("catalyst.config", fromlist=["RuntimeConfig"]).RuntimeConfig(),
                live_config=live_config(),
                journal=journal,
                broker=broker,
                market_data=FakeMarketData(),
                events=(event(),),
                auto_demo=False,
            )
            results = runtime.cycle(now=NOW)
            self.assertEqual(len(results), 1)
            self.assertIsNone(results[0].error)
            self.assertIsNotNone(results[0].decision)
            self.assertIsNotNone(results[0].decision.plan)
            self.assertIsNone(results[0].submission)
            self.assertEqual(delegate.submissions, 0)
            self.assertEqual(len(journal.decisions), 1)
            self.assertTrue(journal.heartbeats)

    def test_runtime_error_is_reported_and_shadow_broker_remains_disarmed(self) -> None:
        with TemporaryDirectory() as directory:
            delegate = FakeDelegate()
            broker = GuardedDemoBroker(
                delegate,
                LocalKillSwitch(Path(directory) / "kill.json"),
            )
            journal = FakeJournal()
            runtime = CatalystRuntime(
                config=__import__("catalyst.config", fromlist=["RuntimeConfig"]).RuntimeConfig(),
                live_config=live_config(),
                journal=journal,
                broker=broker,
                market_data=FakeMarketData(fail=True),
                events=(event(),),
                auto_demo=False,
            )
            result = runtime.cycle(now=NOW)[0]
            self.assertIn("market data unavailable", result.error)
            self.assertFalse(broker.armed)
            self.assertEqual(delegate.disarms, 0)
            self.assertEqual(journal.heartbeats[-1]["status"], "runtime_error")

    def test_events_are_limited_to_runtime_window(self) -> None:
        with TemporaryDirectory() as directory:
            runtime = CatalystRuntime(
                config=__import__("catalyst.config", fromlist=["RuntimeConfig"]).RuntimeConfig(),
                live_config=live_config(),
                journal=FakeJournal(),
                broker=GuardedDemoBroker(
                    FakeDelegate(),
                    LocalKillSwitch(Path(directory) / "kill.json"),
                ),
                market_data=FakeMarketData(),
                events=(event(),),
                auto_demo=False,
            )
            self.assertEqual(runtime.active_events(NOW), (event(),))
            self.assertEqual(runtime.active_events(NOW + timedelta(hours=1)), ())
