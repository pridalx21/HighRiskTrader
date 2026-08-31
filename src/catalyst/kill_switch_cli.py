"""Standalone safety-only kill switch command.

This command can only engage the latch; clearing it requires the authenticated
operator control plane with a healthy audit journal.
"""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path

from catalyst.controls import LocalKillSwitch


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Engage the CATALYST persistent kill switch")
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--reason", default="standalone operator kill switch")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    latch = LocalKillSwitch(args.path)
    latch.engage(occurred_at=datetime.now(UTC), reason=str(args.reason))
    print(f"kill_switch_active={latch.active}")


if __name__ == "__main__":
    main()
