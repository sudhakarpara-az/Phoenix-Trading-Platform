"""
Dhan MarketFeed SDK Verification

Purpose:
- Verify MarketFeed object creation
- Verify connection callbacks
- Verify live tick callbacks
"""

from dotenv import load_dotenv
from dhanhq import DhanContext, MarketFeed

import os

load_dotenv()

CLIENT_ID = os.getenv("DHAN_CLIENT_ID")
ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN")

context = DhanContext(
    CLIENT_ID,
    ACCESS_TOKEN,
)


def on_connect():
    print("\n✅ Connected to Dhan MarketFeed")


def on_close(*args):
    print("\n❌ Connection Closed")


def on_error(error):
    print("\n🚨 Error:", error)


def on_message(message):
    print("\n📩 Raw Message:")
    print(message)


def on_ticks(ticks):
    print("\n📈 Live Tick:")
    print(type(ticks))
    print(ticks)


feed = MarketFeed(
    dhan_context=context,
    instruments=[],
    version="v2",
    on_connect=on_connect,
    on_message=on_message,
    on_close=on_close,
    on_error=on_error,
    on_ticks=on_ticks,
)

print("=" * 70)
print("MarketFeed object created successfully.")
print(feed)
print("=" * 70)