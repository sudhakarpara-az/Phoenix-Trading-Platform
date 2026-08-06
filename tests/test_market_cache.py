from datetime import datetime

from src.market.market_cache import MarketCache
from src.market.market_types import Exchange, MarketTick

cache = MarketCache()

tick = MarketTick(
    exchange=Exchange.NFO,
    symbol="NIFTY",
    security_id="12345",
    ltp=250.75,
    volume=500,
    timestamp=datetime.now(),
)

cache.update(tick)

print("Exists :", cache.exists("12345"))
print("Size   :", cache.size())
print("Tick   :", cache.get("12345"))

cache.remove("12345")

print("Size after remove:", cache.size())