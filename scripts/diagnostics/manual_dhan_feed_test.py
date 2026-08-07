import os

from dhanhq import DhanContext, MarketFeed
from dotenv import load_dotenv
from websockets.exceptions import ConnectionClosed

load_dotenv()


client_id = os.getenv("DHAN_CLIENT_ID")
access_token = os.getenv("DHAN_ACCESS_TOKEN")

if not client_id:
    raise RuntimeError("DHAN_CLIENT_ID missing")

if not access_token:
    raise RuntimeError("DHAN_ACCESS_TOKEN missing")


context = DhanContext(
    client_id,
    access_token,
)


instruments = [
    (
        MarketFeed.IDX,
        "13",
        MarketFeed.Ticker,
    )
]


print("=" * 60)
print("DIRECT DHAN MARKET FEED TEST")
print("=" * 60)

print("Client ID       :", client_id)
print("Exchange        :", MarketFeed.IDX)
print("Security ID     : 13")
print("Request Type    :", MarketFeed.Ticker)
print("Version         : v2")
print("=" * 60)


feed = MarketFeed(
    context,
    instruments,
    "v2",
)


try:

    while True:

        feed.run_forever()

        response = feed.get_data()

        print()
        print("DHAN RESPONSE:")
        print(response)

except ConnectionClosed as exc:

    print()
    print("=" * 60)
    print("DHAN WEBSOCKET CLOSED")
    print("=" * 60)

    print("Exception :", repr(exc))

    print(
        "Close code:",
        getattr(exc, "code", None),
    )

    print(
        "Reason:",
        getattr(exc, "reason", None),
    )

    print(
        "Feed on_close:",
        getattr(feed, "on_close", None),
    )

except Exception as exc:

    print()
    print("DHAN ERROR")
    print(type(exc).__name__)
    print(repr(exc))

finally:

    try:
        feed.close_connection()
    except Exception as exc:
        print("Close warning:", exc)