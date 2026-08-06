# Phoenix Trading Platform
# API Design Specification

**Version:** 1.0

---

# 1. Purpose

This document defines the interfaces between all modules in the Phoenix Trading Platform.

Modules communicate only through well-defined APIs and domain objects.

No module accesses another module's internal implementation.

---

# 2. Module Communication

```
Market Data
      │
      ▼
KS Level Engine
      │
      ▼
Signal Engine
      │
      ▼
Execution Engine
      │
      ▼
Broker Adapter
      │
      ▼
Dhan API
```

---

# 3. Domain Objects

The platform uses strongly typed dataclasses.

```
MarketTick
LevelEvent
Signal
OrderRequest
Order
Position
Trade
```

No dictionaries between modules.

---

# 4. Market Data API

## Responsibilities

- Receive live ticks
- Publish ticks
- Publish option prices
- Publish Greeks (future)

### Methods

```python
connect()

disconnect()

subscribe(symbol)

unsubscribe(symbol)

get_ltp(symbol)

get_option_ltp(strike, side)

get_delta_strike(delta)
```

---

# 5. KS Level Engine API

### Input

```
MarketTick
```

### Output

```
LevelEvent
```

### Methods

```python
calculate_levels()

check_levels()

get_levels()
```

---

# 6. Signal Engine API

### Input

```
LevelEvent
```

### Output

```
Signal
```

### Methods

```python
generate_signal()

validate_signal()

publish_signal()
```

---

# 7. Execution Engine API

### Input

```
Signal
```

### Output

```
OrderRequest
```

### Methods

```python
process_signal()

place_order()

cancel_order()

modify_order()

exit_position()
```

---

# 8. Broker Adapter API

Execution Engine must never call Dhan directly.

### Methods

```python
login()

logout()

place_order()

modify_order()

cancel_order()

get_order()

get_positions()

get_funds()

connect_websocket()
```

---

# 9. Position Manager API

### Methods

```python
open_position()

close_position()

update_position()

get_position()

get_open_positions()

has_open_position(level)
```

---

# 10. Risk Manager API

### Methods

```python
can_trade()

validate_entry()

validate_position()

daily_limits()
```

---

# 11. Telegram Service API

### Methods

```python
send_entry()

send_exit()

send_target()

send_stoploss()

send_error()

send_daily_summary()
```

---

# 12. Database API

### Methods

```python
save_signal()

save_order()

save_trade()

save_position()

save_log()

get_trade_history()
```

---

# 13. Replay Engine API (Future)

```python
load_session()

play()

pause()

resume()

next_tick()

previous_tick()
```

---

# 14. Error Handling

Every API returns either:

```
Success

OR

Phoenix Exception
```

No silent failures.

---

# 15. Logging Standard

Every public API logs:

- Start
- Success
- Failure
- Duration

Example

```
ExecutionEngine.place_order()

START

SUCCESS

Time = 42 ms
```

---

# 16. API Principles

- No circular dependencies
- Strong typing
- No shared mutable state
- One responsibility per API
- Broker-independent interfaces
- Easy unit testing

---

End of Document