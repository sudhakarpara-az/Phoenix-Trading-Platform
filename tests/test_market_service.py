from datetime import datetime

from src.market.market_cache import MarketCache
from src.market.market_data_service import MarketDataService
from src.market.market_types import Exchange, MarketTick


def test_market_data_service() -> None:
    cache = MarketCache()
    service = MarketDataService(cache)

    tick = MarketTick(
        exchange=Exchange.NFO,
        symbol="NIFTY OPTION",
        security_id="12345",
        ltp=125.50,
        volume=100,
        timestamp=datetime.now(),
    )

    service.publish_tick(tick)

    assert service.has_market_data("12345") is True
    assert service.get_ltp("12345") == 125.50
    assert service.get_tick("12345") == tick
    assert service.instrument_count() == 1

    print()
    print("Exists :", service.has_market_data("12345"))
    print("LTP    :", service.get_ltp("12345"))
    print("Tick   :", service.get_tick("12345"))


if __name__ == "__main__":
    test_market_data_service()