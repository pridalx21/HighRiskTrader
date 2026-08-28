from dataclasses import replace
from decimal import Decimal
from unittest import TestCase

from catalyst.config import RuntimeConfig
from catalyst.domain.serialization import canonical_json
from catalyst.engine.pipeline import DecisionPipeline
from tests.fixtures import READY_TIME, broker_contract, demo_account, event, long_market


class CanonicalSerializationTests(TestCase):
    def test_mapping_order_does_not_change_bytes(self) -> None:
        first = canonical_json({"b": 2, "a": Decimal("1.20")})
        second = canonical_json({"a": Decimal("1.20"), "b": 2})
        self.assertEqual(first, second)
        self.assertEqual(first, '{"a":"1.20","b":2}')

    def test_unsupported_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(TypeError, "unsupported"):
            canonical_json({"unsupported"})

    def test_decision_serialization_is_byte_for_byte_repeatable(self) -> None:
        pipeline = DecisionPipeline()
        first = pipeline.evaluate(
            event(),
            long_market(),
            demo_account(),
            READY_TIME,
            contract=broker_contract(),
            auto_demo_armed=True,
        )
        second = pipeline.evaluate(
            event(),
            long_market(),
            demo_account(),
            READY_TIME,
            contract=broker_contract(),
            auto_demo_armed=True,
        )
        self.assertEqual(canonical_json(first), canonical_json(second))

    def test_one_decision_parameter_changes_configuration_hash(self) -> None:
        original = RuntimeConfig()
        changed_strategy = replace(
            original.strategy,
            maximum_data_age_seconds=Decimal("1.9"),
        )
        changed = replace(original, strategy=changed_strategy)
        self.assertNotEqual(original.configuration_hash, changed.configuration_hash)

    def test_storage_path_does_not_change_decision_configuration_hash(self) -> None:
        original = RuntimeConfig()
        changed = replace(
            original,
            storage=replace(original.storage, journal_path="another/local/path.sqlite3"),
        )
        self.assertEqual(original.configuration_hash, changed.configuration_hash)

    def test_rejected_decision_still_contains_configuration_hash(self) -> None:
        decision = DecisionPipeline().evaluate(
            event(),
            long_market(),
            demo_account(),
            READY_TIME,
            contract=broker_contract(),
            auto_demo_armed=False,
        )
        self.assertIsNone(decision.plan)
        self.assertEqual(decision.configuration_hash, RuntimeConfig().configuration_hash)
