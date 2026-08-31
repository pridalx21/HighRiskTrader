"""Deterministic strategy-validation evidence pack.

The harness evaluates frozen observations. It never optimizes parameters or mutates
strategy behavior. All random sampling uses an explicit fixed seed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from json import loads
from pathlib import Path
from random import Random
from typing import Any

from catalyst.domain.serialization import canonical_json, to_canonical_value

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True, slots=True)
class ValidationObservation:
    observation_id: str
    occurred_at: datetime
    event_family: str
    instrument: str
    regime: str
    source: str
    qualified: bool
    traded: bool
    r_after_costs: Decimal | None
    intended_slippage_r: Decimal | None = None
    actual_slippage_r: Decimal | None = None
    excluded_reason: str | None = None

    def __post_init__(self) -> None:
        texts = (
            self.observation_id,
            self.event_family,
            self.instrument,
            self.regime,
            self.source,
        )
        if not all(value.strip() for value in texts):
            raise ValueError("validation observation identifiers must not be empty")
        _require_utc(self.occurred_at, "occurred_at")
        if self.source not in {"historical", "demo"}:
            raise ValueError("validation source must be historical or demo")
        for field_name in (
            "r_after_costs",
            "intended_slippage_r",
            "actual_slippage_r",
        ):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
                raise ValueError(f"{field_name} must be a finite Decimal when present")
        if self.traded and self.r_after_costs is None:
            raise ValueError("traded observations require r_after_costs")
        if not self.traded and self.r_after_costs is not None:
            raise ValueError("non-traded observations must not contain r_after_costs")
        if self.excluded_reason is not None and not self.excluded_reason.strip():
            raise ValueError("excluded_reason must not be empty when present")


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    strategy_version: str
    evaluation_fraction: Decimal = Decimal("0.30")
    walk_forward_folds: int = 4
    bootstrap_iterations: int = 500
    seed: int = 260831
    monthly_loss_cap_r: Decimal = Decimal("4")
    stress_cost_r: Decimal = Decimal("0.15")
    stress_delay_r: Decimal = Decimal("0.10")
    rejection_probability: Decimal = Decimal("0.10")
    missed_fill_probability: Decimal = Decimal("0.15")
    unattended_demo_weeks: Decimal = ZERO

    def __post_init__(self) -> None:
        if not self.strategy_version.strip():
            raise ValueError("strategy_version must not be empty")
        if not ZERO < self.evaluation_fraction < ONE:
            raise ValueError("evaluation_fraction must be between zero and one")
        if self.walk_forward_folds < 1 or self.bootstrap_iterations < 1:
            raise ValueError("walk_forward_folds and bootstrap_iterations must be positive")
        non_negative = (
            "monthly_loss_cap_r",
            "stress_cost_r",
            "stress_delay_r",
            "unattended_demo_weeks",
        )
        for field_name in non_negative:
            value = getattr(self, field_name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO:
                raise ValueError(f"{field_name} must be a finite non-negative Decimal")
        for field_name in ("rejection_probability", "missed_fill_probability"):
            value = getattr(self, field_name)
            if not isinstance(value, Decimal) or not ZERO <= value <= ONE:
                raise ValueError(f"{field_name} must be a Decimal between zero and one")


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be normalized to UTC")


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("occurred_at must be ISO-8601") from exc
    _require_utc(parsed, "occurred_at")
    return parsed


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("validation decimal values must be finite")
    return result


def _boolean(row: dict[str, Any], field_name: str) -> bool:
    value = row.get(field_name)
    if type(value) is not bool:
        raise ValueError(f"{field_name} must be a JSON boolean")
    return value


def load_observations_json(path: str | Path) -> tuple[ValidationObservation, ...]:
    payload = loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("validation input must be a non-empty JSON array")
    observations: list[ValidationObservation] = []
    seen: set[str] = set()
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("validation rows must be JSON objects")
        observation_id = str(row.get("observation_id", ""))
        if observation_id in seen:
            raise ValueError(f"duplicate validation observation_id: {observation_id}")
        seen.add(observation_id)
        excluded_raw = row.get("excluded_reason")
        observations.append(
            ValidationObservation(
                observation_id=observation_id,
                occurred_at=_parse_utc(str(row.get("occurred_at", ""))),
                event_family=str(row.get("event_family", "")),
                instrument=str(row.get("instrument", "")),
                regime=str(row.get("regime", "")),
                source=str(row.get("source", "")),
                qualified=_boolean(row, "qualified"),
                traded=_boolean(row, "traded"),
                r_after_costs=_decimal_or_none(row.get("r_after_costs")),
                intended_slippage_r=_decimal_or_none(row.get("intended_slippage_r")),
                actual_slippage_r=_decimal_or_none(row.get("actual_slippage_r")),
                excluded_reason=(str(excluded_raw) if excluded_raw is not None else None),
            )
        )
    return tuple(sorted(observations, key=lambda item: (item.occurred_at, item.observation_id)))


def _included(rows: tuple[ValidationObservation, ...]) -> tuple[ValidationObservation, ...]:
    return tuple(row for row in rows if row.excluded_reason is None)


def _trade_values(rows: tuple[ValidationObservation, ...]) -> tuple[Decimal, ...]:
    return tuple(
        row.r_after_costs
        for row in rows
        if row.excluded_reason is None and row.traded and row.r_after_costs is not None
    )


def _max_drawdown(values: tuple[Decimal, ...]) -> tuple[Decimal, int]:
    equity = ZERO
    peak = ZERO
    maximum = ZERO
    maximum_duration = 0
    current_duration = 0
    for value in values:
        equity += value
        if equity >= peak:
            peak = equity
            current_duration = 0
            continue
        current_duration += 1
        drawdown = peak - equity
        if drawdown > maximum:
            maximum = drawdown
            maximum_duration = current_duration
    return maximum, maximum_duration


def _longest_losing_streak(values: tuple[Decimal, ...]) -> int:
    longest = 0
    current = 0
    for value in values:
        if value < ZERO:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _profit_factor(values: tuple[Decimal, ...]) -> Decimal | None:
    wins = sum((value for value in values if value > ZERO), ZERO)
    losses = -sum((value for value in values if value < ZERO), ZERO)
    if losses == ZERO:
        return None if wins == ZERO else Decimal("999")
    return wins / losses


def _winner_concentration(values: tuple[Decimal, ...], count: int) -> Decimal:
    positive = sorted((value for value in values if value > ZERO), reverse=True)
    total = sum(positive, ZERO)
    if total == ZERO:
        return ZERO
    return sum(positive[:count], ZERO) / total


def _family_profit_concentration(rows: tuple[ValidationObservation, ...]) -> Decimal:
    profits: dict[str, Decimal] = {}
    for row in rows:
        if row.excluded_reason is not None or not row.traded or row.r_after_costs is None:
            continue
        if row.r_after_costs > ZERO:
            profits[row.event_family] = profits.get(row.event_family, ZERO) + row.r_after_costs
    total = sum(profits.values(), ZERO)
    if total == ZERO:
        return ZERO
    return max(profits.values(), default=ZERO) / total


def _metrics(rows: tuple[ValidationObservation, ...]) -> dict[str, Any]:
    included = _included(rows)
    values = _trade_values(included)
    wins = tuple(value for value in values if value > ZERO)
    losses = tuple(value for value in values if value < ZERO)
    maximum_drawdown, drawdown_duration = _max_drawdown(values)
    trade_count = len(values)
    qualified_count = sum(1 for row in included if row.qualified)
    no_trade_count = sum(1 for row in included if row.qualified and not row.traded)
    expectancy = sum(values, ZERO) / Decimal(trade_count) if trade_count else ZERO
    average_win = sum(wins, ZERO) / Decimal(len(wins)) if wins else ZERO
    average_loss = sum(losses, ZERO) / Decimal(len(losses)) if losses else ZERO
    return {
        "observation_count": len(included),
        "qualified_setup_count": qualified_count,
        "trade_count": trade_count,
        "no_trade_count": no_trade_count,
        "expectancy_r": expectancy,
        "average_win_r": average_win,
        "average_loss_r": average_loss,
        "profit_factor": _profit_factor(values),
        "maximum_drawdown_r": maximum_drawdown,
        "drawdown_duration_trades": drawdown_duration,
        "longest_losing_streak": _longest_losing_streak(values),
        "largest_winner_contribution": _winner_concentration(values, 1),
        "five_largest_winner_contribution": _winner_concentration(values, 5),
        "largest_event_family_profit_contribution": _family_profit_concentration(included),
    }


def _chronological_split(
    historical: tuple[ValidationObservation, ...],
    fraction: Decimal,
) -> tuple[tuple[ValidationObservation, ...], tuple[ValidationObservation, ...]]:
    if len(historical) < 2:
        return historical, ()
    evaluation_count = max(1, int(Decimal(len(historical)) * fraction))
    split_at = max(1, len(historical) - evaluation_count)
    return historical[:split_at], historical[split_at:]


def _walk_forward(
    historical: tuple[ValidationObservation, ...],
    folds: int,
) -> tuple[dict[str, Any], ...]:
    if len(historical) < 3:
        return ()
    fold_size = max(1, len(historical) // (folds + 1))
    reports: list[dict[str, Any]] = []
    for index in range(1, folds + 1):
        train_end = min(len(historical) - 1, fold_size * index)
        test_end = min(len(historical), train_end + fold_size)
        if test_end <= train_end:
            break
        test = historical[train_end:test_end]
        reports.append(
            {
                "fold": index,
                "train_observations": train_end,
                "test_start": test[0].occurred_at,
                "test_end": test[-1].occurred_at,
                "test_metrics": _metrics(test),
            }
        )
    return tuple(reports)


def _group_breakdown(
    rows: tuple[ValidationObservation, ...],
    key_name: str,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[ValidationObservation]] = {}
    for row in _included(rows):
        key = str(getattr(row, key_name))
        groups.setdefault(key, []).append(row)
    return {key: _metrics(tuple(group)) for key, group in sorted(groups.items())}


def _year_breakdown(
    rows: tuple[ValidationObservation, ...],
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[ValidationObservation]] = {}
    for row in _included(rows):
        groups.setdefault(str(row.occurred_at.year), []).append(row)
    return {key: _metrics(tuple(group)) for key, group in sorted(groups.items())}


def _holdouts(
    rows: tuple[ValidationObservation, ...],
    key_name: str,
) -> dict[str, dict[str, Any]]:
    included = _included(rows)
    keys = sorted({str(getattr(row, key_name)) for row in included})
    result: dict[str, dict[str, Any]] = {}
    for key in keys:
        held_out = tuple(row for row in included if str(getattr(row, key_name)) == key)
        remaining = tuple(row for row in included if str(getattr(row, key_name)) != key)
        result[key] = {
            "held_out_metrics": _metrics(held_out),
            "remaining_metrics": _metrics(remaining),
        }
    return result


def _stress_rows(
    rows: tuple[ValidationObservation, ...],
    *,
    penalty: Decimal = ZERO,
    drop_probability: Decimal = ZERO,
    drop_winners_only: bool = False,
    seed: int,
) -> tuple[ValidationObservation, ...]:
    random = Random(seed)
    stressed: list[ValidationObservation] = []
    for row in rows:
        if row.excluded_reason is not None or not row.traded or row.r_after_costs is None:
            stressed.append(row)
            continue
        should_drop = random.random() < float(drop_probability)
        if drop_winners_only and row.r_after_costs <= ZERO:
            should_drop = False
        if should_drop:
            stressed.append(replace(row, traded=False, r_after_costs=None))
        else:
            stressed.append(replace(row, r_after_costs=row.r_after_costs - penalty))
    return tuple(stressed)


def _stress_scenarios(
    rows: tuple[ValidationObservation, ...],
    config: ValidationConfig,
) -> dict[str, dict[str, Any]]:
    return {
        "base": _metrics(rows),
        "wider_spread_commission_slippage": _metrics(
            _stress_rows(rows, penalty=config.stress_cost_r, seed=config.seed + 1)
        ),
        "execution_delay": _metrics(
            _stress_rows(rows, penalty=config.stress_delay_r, seed=config.seed + 2)
        ),
        "broker_rejection": _metrics(
            _stress_rows(
                rows,
                drop_probability=config.rejection_probability,
                seed=config.seed + 3,
            )
        ),
        "missed_winning_fills": _metrics(
            _stress_rows(
                rows,
                drop_probability=config.missed_fill_probability,
                drop_winners_only=True,
                seed=config.seed + 4,
            )
        ),
    }


def _quantile(values: list[Decimal], proportion: Decimal) -> Decimal:
    if not values:
        return ZERO
    ordered = sorted(values)
    index = int((Decimal(len(ordered) - 1) * proportion).to_integral_value())
    return ordered[index]


def _monthly_counts(rows: tuple[ValidationObservation, ...]) -> tuple[int, ...]:
    counts: dict[tuple[int, int], int] = {}
    for row in rows:
        if row.excluded_reason is None and row.traded:
            key = (row.occurred_at.year, row.occurred_at.month)
            counts[key] = counts.get(key, 0) + 1
    return tuple(counts[key] for key in sorted(counts)) or (len(_trade_values(rows)),)


def _bootstrap(
    rows: tuple[ValidationObservation, ...],
    config: ValidationConfig,
) -> dict[str, Any]:
    values = _trade_values(rows)
    if not values:
        return {
            "iterations": config.bootstrap_iterations,
            "expectancy_r_p05": ZERO,
            "expectancy_r_p50": ZERO,
            "expectancy_r_p95": ZERO,
            "max_drawdown_r_p95": ZERO,
            "monthly_loss_cap_breach_probability": ZERO,
        }
    random = Random(config.seed)
    expectancies: list[Decimal] = []
    drawdowns: list[Decimal] = []
    monthly_breaches = 0
    month_counts = _monthly_counts(rows)
    for _ in range(config.bootstrap_iterations):
        sample = tuple(values[random.randrange(len(values))] for _ in range(len(values)))
        expectancies.append(sum(sample, ZERO) / Decimal(len(sample)))
        drawdowns.append(_max_drawdown(sample)[0])
        cursor = 0
        breached = False
        for count in month_counts:
            month_values = sample[cursor : cursor + count]
            cursor += count
            if sum(month_values, ZERO) <= -config.monthly_loss_cap_r:
                breached = True
                break
        if breached:
            monthly_breaches += 1
    return {
        "iterations": config.bootstrap_iterations,
        "expectancy_r_p05": _quantile(expectancies, Decimal("0.05")),
        "expectancy_r_p50": _quantile(expectancies, Decimal("0.50")),
        "expectancy_r_p95": _quantile(expectancies, Decimal("0.95")),
        "max_drawdown_r_p95": _quantile(drawdowns, Decimal("0.95")),
        "monthly_loss_cap_breach_probability": Decimal(monthly_breaches)
        / Decimal(config.bootstrap_iterations),
    }


def _demo_comparison(rows: tuple[ValidationObservation, ...]) -> dict[str, Any]:
    comparable = tuple(
        row
        for row in rows
        if row.source == "demo"
        and row.excluded_reason is None
        and row.intended_slippage_r is not None
        and row.actual_slippage_r is not None
    )
    if not comparable:
        return {
            "comparable_orders": 0,
            "mean_actual_minus_intended_slippage_r": None,
        }
    differences = tuple(
        row.actual_slippage_r - row.intended_slippage_r
        for row in comparable
        if row.actual_slippage_r is not None and row.intended_slippage_r is not None
    )
    return {
        "comparable_orders": len(differences),
        "mean_actual_minus_intended_slippage_r": sum(differences, ZERO) / Decimal(len(differences)),
    }


def _verdict(
    evaluation: dict[str, Any],
    demo_comparison: dict[str, Any],
    config: ValidationConfig,
) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    trade_count = int(evaluation["trade_count"])
    expectancy = Decimal(str(evaluation["expectancy_r"]))
    raw_profit_factor = evaluation["profit_factor"]
    profit_factor = Decimal(str(raw_profit_factor)) if raw_profit_factor is not None else ZERO
    largest_trade = Decimal(str(evaluation["largest_winner_contribution"]))
    family_contribution = Decimal(str(evaluation["largest_event_family_profit_contribution"]))

    if trade_count < 100:
        reasons.append("fewer than 100 untouched evaluation trades")
    if expectancy <= ZERO:
        reasons.append("out-of-sample expectancy is not positive")
    if profit_factor <= Decimal("1.20"):
        reasons.append("out-of-sample profit factor is not above 1.20")
    if largest_trade > Decimal("0.20"):
        reasons.append("single-trade winner concentration exceeds 20%")
    if family_contribution > Decimal("0.50"):
        reasons.append("single event-family profit concentration exceeds 50%")
    if int(demo_comparison["comparable_orders"]) == 0:
        reasons.append("no comparable intended-versus-actual demo orders")
    if config.unattended_demo_weeks < Decimal("8"):
        reasons.append("fewer than 8 weeks of unattended demo evidence")

    if not reasons:
        return "CONTINUE", ()
    if trade_count >= 100 and (expectancy <= ZERO or profit_factor <= ONE):
        return "STOP", tuple(reasons)
    return "REVISE", tuple(reasons)


def run_validation(
    observations: tuple[ValidationObservation, ...],
    config: ValidationConfig,
) -> dict[str, Any]:
    if not observations:
        raise ValueError("validation requires at least one observation")
    ordered = tuple(sorted(observations, key=lambda item: (item.occurred_at, item.observation_id)))
    historical = tuple(
        row for row in ordered if row.source == "historical" and row.excluded_reason is None
    )
    demo = tuple(row for row in ordered if row.source == "demo" and row.excluded_reason is None)
    development, evaluation = _chronological_split(
        historical,
        config.evaluation_fraction,
    )
    excluded = tuple(
        {"observation_id": row.observation_id, "reason": row.excluded_reason}
        for row in ordered
        if row.excluded_reason is not None
    )
    evaluation_metrics = _metrics(evaluation)
    comparison = _demo_comparison(demo)
    verdict, verdict_reasons = _verdict(evaluation_metrics, comparison, config)
    return {
        "strategy_version": config.strategy_version,
        "configuration": config,
        "partitioning": {
            "development_observations": len(development),
            "evaluation_observations": len(evaluation),
            "demo_observations": len(demo),
            "development_end": development[-1].occurred_at if development else None,
            "evaluation_start": evaluation[0].occurred_at if evaluation else None,
        },
        "development": _metrics(development),
        "evaluation": evaluation_metrics,
        "demo": _metrics(demo),
        "walk_forward": _walk_forward(historical, config.walk_forward_folds),
        "event_family_holdouts": _holdouts(evaluation, "event_family"),
        "instrument_holdouts": _holdouts(evaluation, "instrument"),
        "event_family_breakdown": _group_breakdown(evaluation, "event_family"),
        "instrument_breakdown": _group_breakdown(evaluation, "instrument"),
        "year_breakdown": _year_breakdown(evaluation),
        "regime_breakdown": _group_breakdown(evaluation, "regime"),
        "stress_scenarios": _stress_scenarios(evaluation, config),
        "bootstrap_monte_carlo": _bootstrap(evaluation, config),
        "demo_vs_replay": comparison,
        "excluded_observations": excluded,
        "verdict": verdict,
        "verdict_reasons": verdict_reasons,
    }


def _input_hash(observations: tuple[ValidationObservation, ...]) -> str:
    return sha256(canonical_json(observations).encode("utf-8")).hexdigest()


def validation_markdown(report: dict[str, Any]) -> str:
    evaluation = report["evaluation"]
    monte_carlo = report["bootstrap_monte_carlo"]
    reasons = report["verdict_reasons"]
    reason_lines = "\n".join(f"- {reason}" for reason in reasons) or "- none"
    return "\n".join(
        (
            "# CATALYST validation report",
            "",
            f"Strategy version: `{report['strategy_version']}`",
            f"Verdict: **{report['verdict']}**",
            "",
            "## Untouched evaluation",
            "",
            f"- Trades: {evaluation['trade_count']}",
            f"- No-trades: {evaluation['no_trade_count']}",
            f"- Expectancy: {evaluation['expectancy_r']} R",
            f"- Profit factor: {evaluation['profit_factor']}",
            f"- Maximum drawdown: {evaluation['maximum_drawdown_r']} R",
            f"- Longest losing streak: {evaluation['longest_losing_streak']}",
            f"- Five-largest-winner contribution: {evaluation['five_largest_winner_contribution']}",
            "",
            "## Fixed-seed bootstrap / Monte Carlo",
            "",
            f"- Iterations: {monte_carlo['iterations']}",
            "- Expectancy p05/p50/p95: "
            f"{monte_carlo['expectancy_r_p05']} / "
            f"{monte_carlo['expectancy_r_p50']} / "
            f"{monte_carlo['expectancy_r_p95']} R",
            f"- Max drawdown p95: {monte_carlo['max_drawdown_r_p95']} R",
            "- Monthly loss-cap breach probability: "
            f"{monte_carlo['monthly_loss_cap_breach_probability']}",
            "",
            "## Promotion blockers / evidence",
            "",
            reason_lines,
            "",
            f"## {report['verdict']}",
            "",
            "This decision is evidence-based and does not change strategy or risk parameters.",
            "",
        )
    )


def write_evidence_pack(
    observations: tuple[ValidationObservation, ...],
    config: ValidationConfig,
    output_directory: str | Path,
) -> dict[str, str]:
    report = run_validation(observations, config)
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    json_text = canonical_json(to_canonical_value(report)) + "\n"
    markdown_text = validation_markdown(report)
    json_path = output / "validation_report.json"
    markdown_path = output / "validation_report.md"
    json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    manifest = {
        "input_hash": _input_hash(observations),
        "report_json_hash": sha256(json_text.encode("utf-8")).hexdigest(),
        "report_markdown_hash": sha256(markdown_text.encode("utf-8")).hexdigest(),
        "strategy_version": config.strategy_version,
    }
    manifest_text = canonical_json(manifest) + "\n"
    (output / "manifest.json").write_text(manifest_text, encoding="utf-8")
    return {key: str(value) for key, value in manifest.items()}
