# Phoenix Trading Platform
# System Architecture

**Version:** 1.0

---

# 1. Architecture Overview

Phoenix Trading Platform follows a layered, event-driven architecture.

The strategy, execution, and broker are completely independent.

```

```
                   +----------------------+
                   |   Market Data Engine |
                   +----------+-----------+
                              |
                              v
                   +----------------------+
                   |   KS Level Engine    |
                   +----------+-----------+
                              |
                              v
                   +----------------------+
                   |    Signal Engine     |
                   +----------+-----------+
                              |
                              v
                   +----------------------+
                   |    Signal Queue      |
                   +----------+-----------+
                              |
                              v
                   +----------------------+
                   |  Execution Engine    |
                   +----------+-----------+
                              |
                              v
                   +----------------------+
                   |   Position Manager   |
                   +----------+-----------+
                              |
                              v
                   +----------------------+
                   |    Broker Adapter    |
                   +----------+-----------+
                              |
                              v
                          DHAN API
```

---

# 2. Core Modules

## Core

Responsible for:

- Startup
- Logging
- Configuration
- Constants
- Exceptions

No trading logic exists here.

---

## Market Data Engine

Responsibilities

- Connect to Dhan WebSocket
- Receive live ticks
- Publish NIFTY LTP
- Publish Option LTP
- Publish Delta
- Handle reconnects

Output

```
MarketTick
```

---

## KS Level Engine

Responsibilities

- Calculate daily KS levels
- Store K5
- Store K6
- Store K7
- Detect level touch

Output

```
LevelEvent
```

Example

```
{
    level: "K5",
    ltp: 25248.50,
    timestamp: ...
}
```

---

## Signal Engine

Responsibilities

- Validate LevelEvent
- Select option strike
- Read option price
- Build trading signal

Output

```
Signal
```

Example

```
Signal
-------
Signal ID
Timestamp
Side
Strike
Delta
Level
Option Price
Quantity
```

Signal Engine NEVER places orders.

---

## Signal Queue

Responsibilities

- Queue all incoming signals
- Preserve order
- Prevent duplicate processing

FIFO queue.

---

## Execution Engine

Responsibilities

- Read Signal
- Position Lock
- Risk Validation
- Entry Buffer
- Place Limit Order
- Track Order

Output

```
Order
```

---

## Position Manager

Responsibilities

Track every open position.

Information stored

- Trade ID
- Level
- Side
- Strike
- Quantity
- Entry
- SL
- Target
- Current P&L
- Status

---

## Broker Adapter

Responsibilities

Translate platform requests into Dhan API calls.

Example

```
Execution Engine

↓

Buy()

↓

Broker Adapter

↓

Dhan.place_order()
```

The Strategy Engine must never call Dhan directly.

---

## Database Module

Stores

- Signals
- Orders
- Trades
- Logs
- Market Events
- Settings

SQLite initially.

---

## Telegram Module

Receives platform events.

Examples

```
Entry

Target

SL

Errors

Square Off
```

Telegram never communicates with the Strategy Engine.

---

# 3. Event Flow

```
Market Tick

↓

KS Level Event

↓

Signal

↓

Execution

↓

Order

↓

Trade

↓

Notification

↓

Database
```

---

# 4. Object Model

```
MarketTick

↓

LevelEvent

↓

Signal

↓

Order

↓

Trade
```

Each object has a single responsibility.

---

# 5. Threading Model

Thread 1

Market Data

Thread 2

Strategy

Thread 3

Execution

Thread 4

Telegram

Thread 5

Database

Logging is asynchronous.

---

# 6. Design Principles

1. Single Responsibility Principle
2. Dependency Injection
3. Event Driven
4. No Circular Dependencies
5. Configuration Driven
6. Testable Modules
7. Broker Independence

---

# 7. Error Recovery

If Broker Disconnects

```
Reconnect

↓

Resume

↓

Continue
```

If Telegram fails

```
Log Error

↓

Continue Trading
```

If Database fails

```
Retry

↓

Local Cache

↓

Resume
```

Trading must not stop because of a non-critical module.

---

# 8. Future Extensions

Architecture supports

- Zerodha
- AngelOne
- Multiple Strategies
- Multiple Indices
- Replay Engine
- AI Analysis
- Dashboard
- REST API

No core redesign required.

---

End of Document