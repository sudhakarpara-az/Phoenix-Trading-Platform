from src.market.market_service import MarketService
from src.market.tick_processor import TickProcessor

service = MarketService()
processor = TickProcessor(service)

raw_tick = {
    "exchange": "NFO",
    "symbol": "NIFTY",
    "security_id": "12345",
    "ltp": 251.80,
    "volume": 1500,
}

tick = processor.process(raw_tick)

print("Tick:", tick)
print("LTP :", service.get_ltp("12345"))