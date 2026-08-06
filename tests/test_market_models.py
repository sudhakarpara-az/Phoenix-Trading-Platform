from datetime import datetime

from src.market.market_types import Exchange, Instrument, MarketTick


instrument = Instrument(
    exchange=Exchange.NFO,
    symbol="NIFTY 31 JUL 25000 CE",
    security_id="123456",
)

tick = MarketTick(
    exchange=Exchange.NFO,
    symbol=instrument.symbol,
    security_id=instrument.security_id,
    ltp=125.50,
    volume=100,
    timestamp=datetime.now(),
)

print(instrument)
print(tick)