#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m catalyst.demo
PYTHONPATH=src python -m catalyst.replay_demo
