# Data contracts

## General rules

- Internal timestamps are timezone-aware UTC.
- Money and price values are decimal strings at storage boundaries and
  `Decimal` in the domain.
- Logical symbols are stable; broker-specific aliases are configuration.
- Raw provider payloads are stored separately from normalized domain records.
- Every normalized record keeps provider/source identity and ingestion time.
- Missing data stays missing. Do not replace it with zero.

## Economic event

Required fields:

| Field | Type | Rule |
| --- | --- | --- |
| `event_id` | string | Stable and unique per release |
| `name` | string | Human-readable release name |
| `scheduled_at` | UTC datetime | Original scheduled release time |
| `currency` | string | ISO-like currency code |
| `importance` | enum | `LOW`, `MEDIUM`, or `HIGH` |
| `status` | enum | `SCHEDULED` or an explicit fail-closed ineligible status |
| `eligible_symbols` | tuple | Non-empty logical symbols mapped to the event |
| `source` | string | Provider or `manual_csv` |
| `ingested_at` | UTC datetime | When the record entered CATALYST |

Optional fields include actual, consensus, previous, revised previous, unit,
release status, and raw provider identifier. Optional numeric fields use decimal
strings and are contextual only in strategy version 1.

## Market snapshot

The core starter snapshot contains:

- logical symbol;
- snapshot timestamp;
- bid and ask;
- pre-event high and low;
- ATR/volatility scale;
- robust baseline spread;
- current data age;
- deterministic retest-hold result;
- protective stop candidate;
- related markets observed and confirming.
- explicit market-open state.

The feature-builder phase must extend the stored evidence so every derived
value can be reconstructed from raw ticks or bars.

Phase 2 raw replay ticks contain logical symbol, UTC timestamp, bid, ask, and a
non-negative source sequence. Raw bars contain UTC open/close timestamps,
complete bid and ask OHLC values, and source sequence. JSON boundaries require
decimal strings and reject JSON numeric prices, naive/non-UTC time, crossed
quotes, inconsistent bars, duplicate identities, missing fields, and unknown
fields. The replay clock orders by timestamp, record-type priority, symbol, and
source sequence so input file order cannot change the result.

Feature evidence stores the exact pre-event highest ask, lowest bid, median
spread, mean true range from bid/ask bar midpoints, breakout/retest/hold times,
classification, and every available cross-asset vote with its observation
time. Missing related markets create no vote.

## Account snapshot

- account mode (`DEMO`, `REAL`, or `UNKNOWN`);
- currency;
- equity and balance;
- day-start and month-start equity;
- realized daily P&L including fees;
- consecutive losses;
- active correlated risk clusters;
- open worst-case risk counted toward the daily lock;
- snapshot timestamp and broker connection state.

`UNKNOWN` account mode is never equivalent to demo.

## Broker contract

Before sizing, the core requires immutable broker metadata for the logical
symbol: tick size, tick value per one volume unit, contract size, profit and
account currencies, explicit profit-to-account conversion, minimum/maximum/
step volume, commission per volume, and slippage allowance in ticks. Every
decimal is a finite `Decimal`; missing, unknown, off-grid, or internally
inconsistent metadata is rejected.

`commission_per_volume` is the conservative total account-currency commission
for opening and fully closing one volume unit. Broker adapters must normalize
per-side schedules into that round-trip value; an unknown fee schedule fails
closed rather than defaulting to zero.

## Decision record

Each strategy evaluation stores:

- deterministic decision ID and event ID;
- strategy version and configuration hash;
- normalized input references;
- state before and after evaluation;
- every gate result and reason code;
- state and pipeline reason codes;
- selected direction if any;
- risk decision and lock reason;
- complete trade plan if permitted;
- software version/commit;
- decision timestamp.

Canonical decision JSON uses sorted keys, UTC timestamps with `Z`, enum values,
and decimal strings. Accepted and rejected decisions store the deterministic
SHA-256 hash of all decision-affecting configuration.

## Order and fill records

Store request and response separately:

- idempotency key;
- client order ID and broker ticket IDs;
- symbol mapping and contract metadata used for sizing;
- requested entry, stop, take-profit/exit plan, volume, and deviation;
- `order_check` result;
- submission result and broker retcode;
- every fill, partial fill, rejection, cancellation, modification, and close;
- observed spread and slippage at each action.

Never log a password or authentication token.

## Event CSV MVP format

See `config/events.example.csv`. The import must:

- reject naive timestamps;
- reject duplicate `event_id` values;
- reject unknown importance values;
- reject empty event names or currency codes;
- preserve source rows for audit;
- never infer actual/consensus values from prose.

## Storage plan

Phase 2 starts with strict checked-in JSON fixtures and one canonical JSON
report so the deterministic baseline remains standard-library-only. Parquet is
deferred until a licensed historical source and its schema are selected;
SQLite WAL persistence enters with the Phase 3 journal. This temporary boundary
is recorded in ADR-008 and does not couple the domain to JSON.

The complete report embeds raw fixture and expected outcome, derived evidence,
pipeline decision, execution result when applicable, exit, gross P&L,
commission, net P&L and net R, plus configuration, fixture, and report SHA-256
hashes. An absent plan produces no execution attempt rather than a fabricated
fill.

The domain must not depend on these storage choices.
