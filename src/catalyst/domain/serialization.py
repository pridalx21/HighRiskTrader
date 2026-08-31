"""Canonical serialization for deterministic decisions and configuration."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from json import dumps
from typing import Any


def to_canonical_value(value: Any) -> Any:
    """Convert supported immutable domain values into JSON-safe primitives."""

    if isinstance(value, Enum):
        return to_canonical_value(value.value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("cannot serialize a non-finite Decimal")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cannot serialize a naive datetime")
        if value.utcoffset() != timedelta(0):
            raise ValueError("cannot serialize a datetime that is not UTC")
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, timedelta):
        seconds = Decimal(value.days * 86_400 + value.seconds)
        seconds += Decimal(value.microseconds) / Decimal("1000000")
        return str(seconds)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_canonical_value(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical dictionaries require string keys")
        return {key: to_canonical_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_canonical_value(item) for item in value]
    raise TypeError(f"unsupported canonical serialization type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return stable compact JSON with sorted object keys."""

    return dumps(
        to_canonical_value(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_canonical(value: Any) -> str:
    """Hash canonical JSON using a lowercase SHA-256 digest."""

    return sha256(canonical_json(value).encode("utf-8")).hexdigest()
