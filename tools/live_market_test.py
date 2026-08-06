"""
Standalone Dhan Live Market Feed Test
"""

import time

from dhanhq import MarketFeed

from src.broker.dhan_broker import DhanBroker

broker = DhanBroker()

feed = MarketFeed(
    broker.get_context(),
    [
        (MarketFeed.IDX, "13", MarketFeed.Ticker),  # NIFTY 50 Index
    ],
    version="v2",
)

print("Connecting to Dhan Market Feed...")

feed.run_forever()

print("Connected. Waiting for ticks...")

while True:
    try:
        data = feed.get_data()

        if data:
            print("=" * 80)
            print(type(data))
            print(data)

        time.sleep(0.05)

    except KeyboardInterrupt:
        print("Stopping...")
        feed.disconnect()
        break