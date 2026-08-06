from datetime import datetime

from src.strategy.session_manager import SessionManager

session = SessionManager()

print("=" * 50)

test_times = [
    datetime(2026, 1, 1, 9, 0),
    datetime(2026, 1, 1, 9, 20),
    datetime(2026, 1, 1, 11, 0),
    datetime(2026, 1, 1, 15, 14),
    datetime(2026, 1, 1, 15, 15),
]

for dt in test_times:
    print(f"\nTime : {dt.time()}")

    print("Can Trade      :", session.can_trade(dt))
    print("Force Exit     :", session.should_force_exit(dt))
    print("Before Market  :", session.is_before_market(dt))
    print("Market Closed  :", session.is_market_closed(dt))

print("=" * 50)