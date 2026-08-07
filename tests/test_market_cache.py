from datetime import datetime, timedelta

from src.market.market_cache import MarketCache
from src.market.market_types import Exchange, MarketTick


def make_tick(
    security_id: str = "123456",
    ltp: float = 125.50,
    timestamp: datetime | None = None,
) -> MarketTick:
    return MarketTick(
        exchange=Exchange.NFO,
        symbol="NIFTY OPTION",
        security_id=security_id,
        ltp=ltp,
        volume=100,
        timestamp=timestamp or datetime.now(),
    )


def test_cache_stores_tick() -> None:
    cache = MarketCache()
    tick = make_tick()

    cache.update_tick(tick)

    assert cache.get_tick("123456") == tick
    assert cache.get_ltp("123456") == 125.50
    assert cache.size() == 1


def test_cache_updates_with_newer_tick() -> None:
    cache = MarketCache()

    old_time = datetime.now()
    new_time = old_time + timedelta(seconds=1)

    cache.update_tick(make_tick(ltp=100.0, timestamp=old_time))
    cache.update_tick(make_tick(ltp=110.0, timestamp=new_time))

    assert cache.get_ltp("123456") == 110.0


def test_cache_rejects_older_tick() -> None:
    cache = MarketCache()

    new_time = datetime.now()
    old_time = new_time - timedelta(seconds=1)

    cache.update_tick(make_tick(ltp=110.0, timestamp=new_time))
    cache.update_tick(make_tick(ltp=100.0, timestamp=old_time))

    assert cache.get_ltp("123456") == 110.0


def test_cache_returns_none_for_unknown_security_id() -> None:
    cache = MarketCache()

    assert cache.get_tick("999999") is None
    assert cache.get_ltp("999999") is None


def test_cache_exists() -> None:
    cache = MarketCache()

    assert cache.exists("123456") is False

    cache.update_tick(make_tick())

    assert cache.exists("123456") is True


def test_cache_remove() -> None:
    cache = MarketCache()
    cache.update_tick(make_tick())

    assert cache.remove("123456") is True
    assert cache.exists("123456") is False
    assert cache.remove("123456") is False


def test_cache_clear() -> None:
    cache = MarketCache()

    cache.update_tick(make_tick("111111"))
    cache.update_tick(make_tick("222222"))

    assert cache.size() == 2

    cache.clear()

    assert cache.size() == 0


def test_cache_snapshot_is_independent() -> None:
    cache = MarketCache()
    cache.update_tick(make_tick())

    snapshot = cache.snapshot()
    snapshot.clear()

    assert cache.size() == 1