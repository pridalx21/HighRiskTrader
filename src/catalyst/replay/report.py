"""Canonical, byte-stable JSON replay report assembly."""

from __future__ import annotations

from dataclasses import dataclass

from catalyst.domain.serialization import canonical_json, sha256_canonical
from catalyst.replay.runner import ReplayResult


@dataclass(frozen=True, slots=True)
class ReplayReportPayload:
    schema_version: str
    configuration_hash: str
    results: tuple[ReplayResult, ...]


@dataclass(frozen=True, slots=True)
class ReplayReport:
    payload: ReplayReportPayload
    report_hash: str


def build_replay_report(results: tuple[ReplayResult, ...]) -> ReplayReport:
    if not results:
        raise ValueError("replay report requires at least one result")
    ordered = tuple(sorted(results, key=lambda result: result.scenario_id))
    hashes = {result.decision.configuration_hash for result in ordered}
    if len(hashes) != 1:
        raise ValueError("all replay results must use one configuration hash")
    payload = ReplayReportPayload(
        schema_version="catalyst.replay.v1",
        configuration_hash=next(iter(hashes)),
        results=ordered,
    )
    return ReplayReport(payload=payload, report_hash=sha256_canonical(payload))


def replay_report_json(report: ReplayReport) -> str:
    return canonical_json(report)
