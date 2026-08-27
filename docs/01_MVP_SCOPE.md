# MVP scope

## In scope

### Data

- Scheduled high-impact events from a manually maintained CSV first.
- Adapter interface for one later structured calendar provider.
- MT5 tick or one-minute data for a small liquid instrument universe.
- Broker-specific bid, ask, spread, tick size, tick value, and volume limits.
- All timestamps normalized to timezone-aware UTC.

### Strategy

- One Event Reaction Retest playbook.
- A 30-minute pre-event range.
- A configurable post-release no-trade shock window.
- Breakout acceptance, retest hold, cross-asset confirmation, and execution
  quality gates.
- One selected instrument per correlated event cluster.
- Intraday exits only.

### Risk and execution

- Demo accounts only.
- One initial risk unit equal to 5% of current equity by default.
- Maximum daily loss of 3R based on day-start equity.
- Lock after three consecutive losses.
- Protective stop included with the initial order.
- No averaging down or automatic refill.
- Kill switch and broker heartbeat.

### Research and operations

- Historical event replay using the same core pipeline.
- Costs, spread, slippage, timeouts, and rejected fills in replay.
- Append-only decision and order journal.
- Simple read-only dashboard with explicit auto-demo toggle and kill switch.
- Exportable run report and deterministic replay fixture.

## Out of scope

- Real-money trading.
- Unscheduled headline trading.
- Earnings, options, crypto, or overnight positions.
- Machine learning, reinforcement learning, sentiment scoring, or LLM-generated
  numeric signals.
- OpenClaw or n8n inside the signal, risk, or execution path.
- Multiple strategies or portfolio optimization.
- Mobile app, multi-user authentication, billing, or cloud deployment.
- Parameter search intended to maximize historical returns.
- Guaranteed return, win-rate, or drawdown claims.

## Initial event families

- US CPI and core CPI
- US employment report
- FOMC rate decision and statement window
- ECB rate decision
- SNB rate decision

The CSV fixture allows development without selecting a paid provider. Provider
selection happens only after the replay contract is stable.

## Initial market universe

- US100
- US500
- XAUUSD
- EURUSD
- USDJPY
- USDCHF
- GER40

Instrument names are logical identifiers. Broker symbols and contract details
must be mapped explicitly in `config/instruments.example.toml`.

## Non-functional requirements

- A clean machine can run core tests without MT5 or network access.
- A deterministic replay returns the same decision sequence for the same input.
- A process restart cannot duplicate an already-submitted event order.
- Any unrecognized account mode, order status, or data condition is rejected.
- The operator can reconstruct a decision from the journal alone.

