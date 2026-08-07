import pytest
from src.market.market_types import Exchange, Instrument, TickType
from src.market.subscription_manager import (
    MarketSubscription,
    SubscriptionManager,
)


def make_instrument(
    security_id: str = "123456",
    exchange: Exchange = Exchange.NFO,
    symbol: str = "NIFTY OPTION",
) -> Instrument:
    return Instrument(
        exchange=exchange,
        symbol=symbol,
        security_id=security_id,
    )


def test_add_subscription() -> None:
    manager = SubscriptionManager()
    instrument = make_instrument()

    subscription = manager.add(
        instrument=instrument,
        tick_type=TickType.LTP,
    )

    assert isinstance(subscription, MarketSubscription)
    assert subscription.instrument == instrument
    assert subscription.tick_type is TickType.LTP
    assert manager.count() == 1


def test_duplicate_subscription_is_not_added_twice() -> None:
    manager = SubscriptionManager()
    instrument = make_instrument()

    first = manager.add(instrument, TickType.LTP)
    second = manager.add(instrument, TickType.LTP)

    assert first == second
    assert manager.count() == 1


def test_subscription_upgrades_to_higher_mode() -> None:
    manager = SubscriptionManager()
    instrument = make_instrument()

    manager.add(instrument, TickType.LTP)
    upgraded = manager.add(instrument, TickType.FULL)

    assert upgraded.tick_type is TickType.FULL
    assert manager.count() == 1


def test_subscription_does_not_downgrade() -> None:
    manager = SubscriptionManager()
    instrument = make_instrument()

    manager.add(instrument, TickType.FULL)
    result = manager.add(instrument, TickType.LTP)

    assert result.tick_type is TickType.FULL
    assert manager.count() == 1


def test_get_subscription() -> None:
    manager = SubscriptionManager()
    instrument = make_instrument()

    manager.add(instrument, TickType.QUOTE)

    result = manager.get(
        exchange=Exchange.NFO,
        security_id="123456",
    )

    assert result is not None
    assert result.instrument == instrument
    assert result.tick_type is TickType.QUOTE


def test_get_unknown_subscription_returns_none() -> None:
    manager = SubscriptionManager()

    result = manager.get(
        exchange=Exchange.NFO,
        security_id="999999",
    )

    assert result is None


def test_contains_subscription() -> None:
    manager = SubscriptionManager()
    instrument = make_instrument()

    assert manager.contains(Exchange.NFO, "123456") is False

    manager.add(instrument)

    assert manager.contains(Exchange.NFO, "123456") is True


def test_remove_subscription() -> None:
    manager = SubscriptionManager()
    instrument = make_instrument()

    manager.add(instrument)

    assert manager.remove(Exchange.NFO, "123456") is True
    assert manager.count() == 0
    assert manager.remove(Exchange.NFO, "123456") is False


def test_list_all_returns_all_subscriptions() -> None:
    manager = SubscriptionManager()

    manager.add(
        make_instrument(
            security_id="111111",
            exchange=Exchange.IDX,
            symbol="NIFTY 50",
        )
    )

    manager.add(
        make_instrument(
            security_id="222222",
            exchange=Exchange.NFO,
            symbol="NIFTY CALL",
        )
    )

    subscriptions = manager.list_all()

    assert isinstance(subscriptions, tuple)
    assert len(subscriptions) == 2


def test_list_by_exchange() -> None:
    manager = SubscriptionManager()

    manager.add(
        make_instrument(
            security_id="111111",
            exchange=Exchange.NSE,
            symbol="NIFTY 50",
        )
    )

    manager.add(
        make_instrument(
            security_id="222222",
            exchange=Exchange.NFO,
            symbol="NIFTY CALL",
        )
    )

    manager.add(
        make_instrument(
            security_id="333333",
            exchange=Exchange.NFO,
            symbol="NIFTY PUT",
        )
    )

    nfo_subscriptions = manager.list_by_exchange(Exchange.NFO)

    assert len(nfo_subscriptions) == 2
    assert all(
        subscription.instrument.exchange is Exchange.NFO
        for subscription in nfo_subscriptions
    )


def test_clear_subscriptions() -> None:
    manager = SubscriptionManager()

    manager.add(make_instrument("111111"))
    manager.add(make_instrument("222222"))

    assert manager.count() == 2

    manager.clear()

    assert manager.count() == 0


def test_empty_security_id_is_rejected() -> None:
    manager = SubscriptionManager()

    try:
        manager.get(Exchange.NFO, " ")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "security_id cannot be empty"