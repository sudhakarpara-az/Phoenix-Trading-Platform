from src.market.market_cache import MarketCache
from src.market.market_data_service import MarketDataService
from src.market.market_types import Exchange, Instrument, TickType
from src.market.subscription_manager import SubscriptionManager
from src.market.tick_processor import TickProcessor


def test_websocket_client_pipeline() -> None:
    cache = MarketCache()
    service = MarketDataService(cache)

    subscriptions = SubscriptionManager()

    nifty = Instrument(
        exchange=Exchange.IDX,
        symbol="NIFTY 50",
        security_id="13",
    )

    subscriptions.add(
        instrument=nifty,
        tick_type=TickType.LTP,
    )

    processor = TickProcessor(
        market_data_service=service,
        subscription_manager=subscriptions,
    )

    raw_message = {
        "type": "Ticker Data",
        "security_id": "13",
        "LTP": 24850.50,
    }

    tick = processor.process(raw_message)

    assert tick is not None
    assert tick.security_id == "13"
    assert tick.symbol == "NIFTY 50"
    assert tick.ltp == 24850.50
    assert service.get_ltp("13") == 24850.50

    print()
    print("WebSocket pipeline simulation successful.")
    print("Tick:", tick)


if __name__ == "__main__":
    test_websocket_client_pipeline()