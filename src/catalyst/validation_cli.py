"""Command-line entry point for the deterministic validation harness."""

from __future__ import annotations

from argparse import ArgumentParser
from decimal import Decimal
from pathlib import Path

from catalyst.validation import ValidationConfig, load_observations_json, write_evidence_pack


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Build a CATALYST validation evidence pack")
    parser.add_argument("input", type=Path, help="JSON observation file")
    parser.add_argument("output", type=Path, help="output directory")
    parser.add_argument("--strategy-version", required=True)
    parser.add_argument("--seed", type=int, default=260831)
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--unattended-demo-weeks", default="0")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    observations = load_observations_json(args.input)
    config = ValidationConfig(
        strategy_version=str(args.strategy_version),
        seed=int(args.seed),
        bootstrap_iterations=int(args.iterations),
        unattended_demo_weeks=Decimal(str(args.unattended_demo_weeks)),
    )
    manifest = write_evidence_pack(observations, config, args.output)
    for key, value in sorted(manifest.items()):
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
