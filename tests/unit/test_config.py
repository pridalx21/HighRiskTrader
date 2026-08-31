from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from tomllib import load
from unittest import TestCase

from catalyst.config import RuntimeConfig, load_runtime_config, parse_runtime_config

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "settings.example.toml"


def example_config_data():
    with CONFIG_PATH.open("rb") as handle:
        return load(handle)


class RuntimeConfigTests(TestCase):
    def test_checked_in_example_loads_with_safe_defaults(self) -> None:
        config = load_runtime_config(CONFIG_PATH)
        self.assertTrue(config.system.demo_only)
        self.assertFalse(config.system.auto_demo_armed)
        self.assertEqual(config.system.timezone, "UTC")
        self.assertEqual(config.risk.policy.risk_fraction.as_tuple().exponent, -2)
        self.assertEqual(len(config.configuration_hash), 64)

    def test_configuration_hash_is_repeatable(self) -> None:
        self.assertEqual(
            load_runtime_config(CONFIG_PATH).configuration_hash,
            load_runtime_config(CONFIG_PATH).configuration_hash,
        )

    def test_tighter_risk_fraction_is_allowed(self) -> None:
        data = example_config_data()
        data["risk"]["risk_fraction"] = "0.04"
        config = parse_runtime_config(data)
        self.assertEqual(str(config.risk.policy.risk_fraction), "0.04")

    def test_float_risk_fraction_is_rejected(self) -> None:
        data = example_config_data()
        data["risk"]["risk_fraction"] = 0.05
        with self.assertRaisesRegex(ValueError, "must be str"):
            parse_runtime_config(data)

    def test_risk_fraction_above_approved_default_is_rejected(self) -> None:
        data = example_config_data()
        data["risk"]["risk_fraction"] = "0.06"
        with self.assertRaisesRegex(ValueError, "0.05"):
            parse_runtime_config(data)

    def test_demo_only_false_is_rejected(self) -> None:
        data = example_config_data()
        data["system"]["demo_only"] = False
        with self.assertRaisesRegex(ValueError, "demo_only"):
            parse_runtime_config(data)

    def test_non_utc_timezone_is_rejected(self) -> None:
        data = example_config_data()
        data["system"]["timezone"] = "Europe/Zurich"
        with self.assertRaisesRegex(ValueError, "timezone must equal UTC"):
            parse_runtime_config(data)

    def test_unknown_key_is_rejected(self) -> None:
        data = example_config_data()
        data["strategy"]["secret_override"] = True
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            parse_runtime_config(data)

    def test_missing_key_is_rejected(self) -> None:
        data = example_config_data()
        del data["execution"]["require_initial_stop"]
        with self.assertRaisesRegex(ValueError, "missing keys"):
            parse_runtime_config(data)

    def test_initial_stop_cannot_be_disabled(self) -> None:
        data = example_config_data()
        data["execution"]["require_initial_stop"] = False
        with self.assertRaisesRegex(ValueError, "require_initial_stop"):
            parse_runtime_config(data)

    def test_averaging_down_cannot_be_enabled(self) -> None:
        data = example_config_data()
        data["risk"]["allow_averaging_down"] = True
        with self.assertRaisesRegex(ValueError, "allow_averaging_down"):
            parse_runtime_config(data)

    def test_overnight_exposure_cannot_be_enabled(self) -> None:
        data = example_config_data()
        data["risk"]["allow_overnight"] = True
        with self.assertRaisesRegex(ValueError, "allow_overnight"):
            parse_runtime_config(data)

    def test_blind_order_retry_cannot_be_enabled(self) -> None:
        data = example_config_data()
        data["execution"]["blind_order_retry"] = True
        with self.assertRaisesRegex(ValueError, "blind_order_retry"):
            parse_runtime_config(data)

    def test_multiple_submit_attempts_are_rejected(self) -> None:
        data = example_config_data()
        data["execution"]["maximum_submit_attempts"] = 2
        with self.assertRaisesRegex(ValueError, "maximum_submit_attempts"):
            parse_runtime_config(data)

    def test_non_finite_decimal_string_is_rejected(self) -> None:
        data = example_config_data()
        data["strategy"]["maximum_spread_multiple"] = "NaN"
        with self.assertRaisesRegex(ValueError, "must be finite"):
            parse_runtime_config(data)

    def test_strategy_and_state_timings_cannot_diverge(self) -> None:
        config = RuntimeConfig()
        mismatched_state = replace(
            config.state_machine,
            shock_window=timedelta(seconds=91),
        )
        with self.assertRaisesRegex(ValueError, "shock windows must match"):
            replace(config, state_machine=mismatched_state)

    def test_malformed_toml_is_reported_as_value_error(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bad.toml"
            path.write_text("[system\ndemo_only = true", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid TOML"):
                load_runtime_config(path)

    def test_parsing_does_not_mutate_source_mapping(self) -> None:
        data = example_config_data()
        original = deepcopy(data)
        parse_runtime_config(data)
        self.assertEqual(data, original)
