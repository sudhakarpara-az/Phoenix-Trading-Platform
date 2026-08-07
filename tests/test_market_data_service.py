from datetime import datetime

from src.market.market_cache import MarketCache
from src.market.market_data_service import MarketDataService
from src.market.market_types import Exchange, MarketTick


def make_tick(
    security_id: str = "123456",
    ltp: float = 125.50,
) -> MarketTick:
    return MarketTick(
        exchange=Exchange.NFO,
        symbol="NIFTY OPTION",
        security_id=security_id,
        ltp=ltp,
        volume=100,
        timestamp=datetime.now(),
    )


def test_service_publishes_and_reads_tick() -> None:
    cache = MarketCache()
    service = MarketDataService(cache)

    tick = make_tick()

    service.publish_tick(tick)

    assert service.get_tick("123456") == tick
    assert service.get_ltp("123456") == 125.50


def test_service_reports_market_data_presence() -> None:
    cache = MarketCache()
    service = MarketDataService(cache)

    assert service.has_market_data("123456") is False

    service.publish_tick(make_tick())

    assert service.has_market_data("123456") is True


def test_service_returns_none_for_unknown_instrument() -> None:
    service = MarketDataService(MarketCache())

    assert service.get_tick("999999") is None
    assert service.get_ltp("999999") is None


def test_service_tracks_multiple_instruments() -> None:
    service = MarketDataService(MarketCache())

    service.publish_tick(make_tick("111111", 100.0))
    service.publish_tick(make_tick("222222", 200.0))

    assert service.instrument_count() == 2
    assert service.get_ltp("111111") == 100.0
    assert service.get_ltp("222222") == 200.0


def test_service_remove() -> None:
    service = MarketDataService(MarketCache())

    service.publish_tick(make_tick())

    assert service.remove("123456") is True
    assert service.get_tick("123456") is None


def test_service_clear() -> None:
    service = MarketDataService(MarketCache())

    service.publish_tick(make_tick("111111", 100.0))
    service.publish_tick(make_tick("222222", 200.0))

    service.clear()

    assert service.instrument_count() == 0


def test_service_snapshot_is_independent() -> None:
    service = MarketDataService(MarketCache())

    service.publish_tick(make_tick())

    snapshot = service.snapshot()
    snapshot.clear()

    assert service.instrument_count() == 1