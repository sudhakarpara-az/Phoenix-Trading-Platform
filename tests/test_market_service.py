from datetime import datetime

from src.market.market_service import MarketService
from src.market.market_types import Exchange, MarketTick


service = MarketService()

tick = MarketTick(
    exchange=Exchange.NFO,
    symbol="NIFTY",
    security_id="12345",
    ltp=251.35,
    volume=1000,
    timestamp=datetime.now(),
)

service.update_tick(tick)

print("Exists :", service.exists("12345"))
print("LTP    :", service.get_ltp("12345"))
print("Tick   :", service.get_tick("12345"))
print("Size   :", service.cache_size())

service.clear()

print("Size After Clear :", service.cache_size())