from src.market.market_types import Exchange, Instrument
from src.market.subscription_manager import SubscriptionManager

manager = SubscriptionManager()

nifty = Instrument(
    exchange=Exchange.NSE,
    symbol="NIFTY 50",
    security_id="13",
)

manager.subscribe(nifty)

print("Count:", manager.count())
print("Subscribed:", manager.is_subscribed("13"))
print("Instrument:", manager.get("13"))

manager.unsubscribe("13")

print("Count after remove:", manager.count())