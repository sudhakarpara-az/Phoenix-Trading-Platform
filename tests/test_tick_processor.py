from datetime import datetime

from src.market.market_cache import MarketCache
from src.market.market_data_service import MarketDataService
from src.market.market_types import (
    Exchange,
    Instrument,
    TickType,
)
from src.market.subscription_manager import SubscriptionManager
from src.market.tick_processor import TickProcessor


def build_processor():
    cache = MarketCache()
    market_data = MarketDataService(cache)
    subscriptions = SubscriptionManager()

    instrument = Instrument(
        exchange=Exchange.IDX,
        symbol="NIFTY 50",
        security_id="13",
    )

    subscriptions.add(
        instrument,
        TickType.LTP,
    )

    processor = TickProcessor(
        market_data_service=market_data,
        subscription_manager=subscriptions,
    )

    return processor, market_data


def test_process_valid_ticker_message() -> None:
    processor, market_data = build_processor()

    message = {
        "type": "Ticker Data",
        "security_id": "13",
        "LTP": 24850.50,
        "LTT": 1723000000,
    }

    tick = processor.process(message)

    assert tick is not None
    assert tick.security_id == "13"
    assert tick.symbol == "NIFTY 50"
    assert tick.ltp == 24850.50
    assert tick.tick_type is TickType.LTP

    assert market_data.get_ltp("13") == 24850.50


def test_process_quote_message() -> None:
    processor, _ = build_processor()

    message = {
        "type": "Quote Data",
        "security_id": "13",
        "LTP": 24851.00,
        "volume": 1500,
        "LTT": 1723000000,
    }

    tick = processor.process(message)

    assert tick is not None
    assert tick.tick_type is TickType.QUOTE
    assert tick.volume == 1500


def test_process_full_message() -> None:
    processor, _ = build_processor()

    message = {
        "response_code": 8,
        "security_id": "13",
        "LTP": 24852.00,
        "volume": 2000,
        "LTT": 1723000000,
    }

    tick = processor.process(message)

    assert tick is not None
    assert tick.tick_type is TickType.FULL


def test_numeric_ticker_response_code() -> None:
    processor, _ = build_processor()

    message = {
        "response_code": 2,
        "security_id": "13",
        "LTP": 24853.00,
    }

    tick = processor.process(message)

    assert tick is not None
    assert tick.tick_type is TickType.LTP


def test_unknown_security_id_is_ignored() -> None:
    processor, market_data = build_processor()

    message = {
        "type": "Ticker Data",
        "security_id": "999999",
        "LTP": 100.0,
    }

    result = processor.process(message)

    assert result is None
    assert market_data.get_tick("999999") is None


def test_missing_security_id_is_ignored() -> None:
    processor, _ = build_processor()

    message = {
        "type": "Ticker Data",
        "LTP": 24850.0,
    }

    assert processor.process(message) is None


def test_missing_ltp_is_ignored() -> None:
    processor, _ = build_processor()

    message = {
        "type": "Ticker Data",
        "security_id": "13",
    }

    assert processor.process(message) is None


def test_zero_ltp_is_ignored() -> None:
    processor, _ = build_processor()

    message = {
        "type": "Ticker Data",
        "security_id": "13",
        "LTP": 0,
    }

    assert processor.process(message) is None


def test_invalid_ltp_is_ignored() -> None:
    processor, _ = build_processor()

    message = {
        "type": "Ticker Data",
        "security_id": "13",
        "LTP": "INVALID",
    }

    assert processor.process(message) is None


def test_non_market_packet_is_ignored() -> None:
    processor, _ = build_processor()

    message = {
        "response_code": 6,
        "security_id": "13",
        "LTP": 24800.0,
    }

    assert processor.process(message) is None


def test_ticker_without_volume_defaults_to_zero() -> None:
    processor, _ = build_processor()

    message = {
        "type": "Ticker Data",
        "security_id": "13",
        "LTP": 24850.0,
    }

    tick = processor.process(message)

    assert tick is not None
    assert tick.volume == 0


def test_negative_volume_becomes_zero() -> None:
    processor, _ = build_processor()

    message = {
        "type": "Quote Data",
        "security_id": "13",
        "LTP": 24850.0,
        "volume": -100,
    }

    tick = processor.process(message)

    assert tick is not None
    assert tick.volume == 0


def test_datetime_timestamp_is_preserved() -> None:
    processor, _ = build_processor()

    now = datetime.now()

    message = {
        "type": "Ticker Data",
        "security_id": "13",
        "LTP": 24850.0,
        "timestamp": now,
    }

    tick = processor.process(message)

    assert tick is not None
    assert tick.timestamp == now


def test_non_dict_message_is_ignored() -> None:
    processor, _ = build_processor()

    assert processor.process("invalid message") is None