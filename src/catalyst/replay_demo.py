"""Run all checked-in synthetic replay fixtures and print canonical JSON."""

from pathlib import Path

from catalyst.config import load_runtime_config
from catalyst.replay.fixture import load_replay_fixture
from catalyst.replay.report import build_replay_report, replay_report_json
from catalyst.replay.runner import ReplayRunner


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config = load_runtime_config(project_root / "config" / "settings.example.toml")
    fixture_paths = sorted((project_root / "tests" / "data" / "replay").glob("*.json"))
    if not fixture_paths:
        raise SystemExit("no replay fixtures found")
    runner = ReplayRunner(config)
    results = tuple(runner.run(load_replay_fixture(path)) for path in fixture_paths)
    mismatches = [result.scenario_id for result in results if not result.expected_match]
    if mismatches:
        raise SystemExit(f"replay expectation mismatch: {', '.join(mismatches)}")
    print(replay_report_json(build_replay_report(results)))


if __name__ == "__main__":
    main()
