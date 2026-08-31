"""Release-candidate repository hygiene checks.

The check intentionally focuses on tracked artifacts and high-confidence secret
material. It does not replace broker credential rotation or GitHub secret scanning.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

FORBIDDEN_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".pyc",
    ".ex4",
    ".ex5",
    ".pem",
    ".key",
}
FORBIDDEN_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
}
# Build the markers from fragments so this scanner does not match its own source
# while still detecting the exact assembled markers in every other tracked file.
PRIVATE_KEY_MARKERS = (
    "-----BEGIN " + "PRIVATE KEY-----",
    "-----BEGIN " + "RSA PRIVATE KEY-----",
    "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
)


def tracked_files() -> tuple[Path, ...]:
    output = subprocess.check_output(["git", "ls-files", "-z"])
    return tuple(Path(item.decode("utf-8")) for item in output.split(b"\0") if item)


def _is_environment_example(name: str) -> bool:
    return name == ".env.example" or (name.startswith(".env.") and name.endswith(".example"))


def violations(files: tuple[Path, ...]) -> tuple[str, ...]:
    problems: list[str] = []
    for path in files:
        lowered_parts = {part.lower() for part in path.parts}
        name = path.name.lower()
        if (name == ".env" or name.startswith(".env.")) and not _is_environment_example(name):
            problems.append(f"tracked environment secret file: {path}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(f"tracked runtime/secret artifact: {path}")
        if lowered_parts & FORBIDDEN_PARTS:
            problems.append(f"tracked generated cache: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for marker in PRIVATE_KEY_MARKERS:
            if marker in text:
                problems.append(f"private key material marker in tracked file: {path}")
    return tuple(problems)


def main() -> None:
    problems = violations(tracked_files())
    if problems:
        for problem in problems:
            print(problem)
        raise SystemExit(1)
    print("release_hygiene=pass")


if __name__ == "__main__":
    main()
