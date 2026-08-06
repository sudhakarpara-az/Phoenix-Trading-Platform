# Phoenix Trading Platform
# Functional Specification

**Document Version:** 1.0

---

# 1. Purpose

This document defines the functional behavior of the Phoenix Trading Platform.

It specifies:

- Business Rules
- Trading Rules
- Workflow
- System Behaviour
- Order Lifecycle
- Position Management
- Risk Management

This document is the primary reference for development.

---

# 2. Trading Session

## Trading Instrument

Underlying

- NIFTY 50 Index

Trading Instrument

- NIFTY CE
- NIFTY PE

Trading Type

- Intraday

Position Type

- BUY ONLY

No option selling.

---

# 3. Trading Schedule

| Event | Time |
|---------|------|
| Market Opens | 09:15 |
| Strategy Starts | 09:20 |
| New Entries Allowed Until | 15:15 |
| Force Exit | 15:15 |

No overnight positions.

---

# 4. Strategy Overview

The Phoenix Strategy continuously monitors the underlying NIFTY LTP.

It never waits for candle close.

Signals are generated immediately when LTP reaches predefined KS Levels.

---

# 5. KS Levels

The strategy uses:

- K5
- K6
- K7

These levels are calculated every trading day using the KS Pine Script.

---

# 6. Market Data Flow

```
NIFTY Tick

↓

Market Data Engine

↓

Current LTP

↓

KS Monitor

↓

Signal Generator
```

The Market Data Engine continuously publishes LTP updates.

---

# 7. Entry Workflow

```
Underlying LTP

↓

Touches K5/K6/K7

↓

Generate Signal

↓

Select Option Strike

↓

Read Option Price

↓

Apply Entry Buffer

↓

Place BUY LIMIT Order
```

---

# 8. Option Selection

For every signal:

Select:

Delta

0.59

↓

0.69

Nearest strike only.

Both CALL and PUT are monitored independently.

---

# 9. Entry Buffer

Purpose:

Reduce slippage.

Example

```
Signal Price

100
```

Allowed Entry

```
100

↓

101
```

Configurable.

```
strategy.yaml

entry_buffer = 1
```

---

# 10. Position Lock Rule

One active trade per KS level.

Example

```
CALL

K5

OPEN
```

Ignore all additional K5 entries until:

- Stop Loss
- Target
- Manual Exit
- End-of-Day Exit

K6 remains eligible.

K7 remains eligible.

---

# 11. Re-entry Rule

Unlimited.

Condition:

Previous trade on same KS level must be closed.

---

# 12. Duplicate Prevention

The Execution Engine must reject:

- Duplicate orders
- Duplicate signals
- Multiple active positions on same level

---

# 13. Signal Validation

Before placing any order:

Validate:

✓ Trading Hours

✓ Broker Connected

✓ Strategy Enabled

✓ Position Lock

✓ Delta Available

✓ Strike Available

✓ Market Open

If any validation fails:

Signal is discarded.

---

# 14. Order Lifecycle

```
NEW SIGNAL

↓

VALIDATED

↓

LIMIT ORDER

↓

PENDING

↓

FILLED

↓

POSITION OPEN

↓

SL / TARGET

↓

POSITION CLOSED
```

---

# 15. Trade States

Each trade has one of the following states.

- Waiting
- Triggered
- Order Submitted
- Pending
- Executed
- Open
- Target Hit
- Stop Loss Hit
- Cancelled
- Closed

---

# 16. Position Management

Track:

- Trade ID
- KS Level
- Side
- Strike
- Delta
- Entry
- Quantity
- SL
- Target
- Current P&L
- Status

---

# 17. End-of-Day Logic

At exactly 15:15

```
Open Position

↓

Market Exit

↓

Trade Closed
```

No new entries after 15:15.

---

# 18. Logging

Every event must be recorded.

Examples

- Signal Generated
- Signal Rejected
- Order Submitted
- Order Filled
- Order Modified
- Target Hit
- Stop Loss
- Exit
- Error

---

# 19. Telegram Notifications

The following events generate notifications.

- Entry
- Exit
- SL
- Target
- Force Exit
- System Errors

---

# 20. Error Handling

Examples

Broker Offline

↓

Retry

↓

Notify User

↓

Continue Monitoring

Critical errors must never terminate the application unexpectedly.

---

# 21. Paper Trading

Paper Trading uses the same Strategy Engine.

Only the Execution Engine changes.

```
Strategy

↓

Paper Execution
```

---

# 22. Live Trading

```
Strategy

↓

Live Execution

↓

Dhan API
```

Strategy remains unchanged.

---

# 23. Configuration

The following values are configurable.

- Quantity
- Entry Buffer
- SL
- Target
- Telegram
- Trading Window
- Delta Range

---

# 24. Acceptance Criteria

The platform is functionally complete when:

✓ KS Levels calculated correctly

✓ Signals generated correctly

✓ Correct strike selected

✓ Limit order placed

✓ Position tracked

✓ Exit executed

✓ Telegram notification sent

✓ Trade stored in database

---

End of Document