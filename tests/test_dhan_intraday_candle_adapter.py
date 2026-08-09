"""
Tests for Dhan historical one-minute candle normalization.
"""

from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest

from src.market.candle_builder import (
    HistoricalCandle,
)
from src.market.dhan_intraday_candle_adapter import (
    DhanIntradayCandleAdapter,
)


CANDLE_START = datetime(
    2026,
    8,
    10,
    9,
    15,
)

REQUESTED_AT = datetime(
    2026,
    8,
    10,
    9,
    16,
)

IST = timezone(
    timedelta(
        hours=5,
        minutes=30,
    )
)


def epoch_for(
    value: datetime,
) -> int:
    aware = value.replace(
        tzinfo=IST
    )

    return int(
        aware.timestamp()
    )


def make_payload(
    *,
    timestamp: datetime = CANDLE_START,
) -> dict:
    return {
        "open": [
            100.0,
        ],
        "high": [
            108.0,
        ],
        "low": [
            97.0,
        ],
        "close": [
            105.0,
        ],
        "volume": [
            1000,
        ],
        "timestamp": [
            epoch_for(
                timestamp
            ),
        ],
    }


class FakeDhanClient:
    def __init__(
        self,
        response,
    ) -> None:
        self.response = response
        self.calls = []

    def intraday_minute_data(
        self,
        security_id,
        exchange_segment,
        instrument_type,
        from_date,
        to_date,
        interval=1,
        oi=False,
    ):
        self.calls.append(
            {
                "security_id": security_id,
                "exchange_segment": (
                    exchange_segment
                ),
                "instrument_type": (
                    instrument_type
                ),
                "from_date": from_date,
                "to_date": to_date,
                "interval": interval,
                "oi": oi,
            }
        )

        return self.response


def test_fetches_exact_nifty_option_minute() -> None:
    client = FakeDhanClient(
        make_payload()
    )

    adapter = DhanIntradayCandleAdapter(
        client
    )

    candle = adapter.get_one_minute_candle(
        security_id="12345",
        symbol="NIFTY-20260813-24500-CE",
        candle_start=CANDLE_START,
        requested_at=REQUESTED_AT,
    )

    assert isinstance(
        candle,
        HistoricalCandle,
    )

    assert candle.security_id == "12345"

    assert (
        candle.symbol
        == "NIFTY-20260813-24500-CE"
    )

    assert candle.start_time == CANDLE_START

    assert candle.end_time == datetime(
        2026,
        8,
        10,
        9,
        16,
    )

    assert candle.open == 100.0
    assert candle.high == 108.0
    assert candle.low == 97.0
    assert candle.close == 105.0


def test_dhan_request_uses_option_contract_scope() -> None:
    client = FakeDhanClient(
        make_payload()
    )

    adapter = DhanIntradayCandleAdapter(
        client
    )

    adapter.get_one_minute_candle(
        security_id="12345",
        symbol="NIFTY-TEST-CE",
        candle_start=CANDLE_START,
        requested_at=REQUESTED_AT,
    )

    assert client.calls == [
        {
            "security_id": "12345",
            "exchange_segment": "NSE_FNO",
            "instrument_type": "OPTIDX",
            "from_date": (
                "2026-08-10 09:15:00"
            ),
            "to_date": (
                "2026-08-10 09:16:00"
            ),
            "interval": 1,
            "oi": False,
        }
    ]


def test_success_envelope_is_supported() -> None:
    client = FakeDhanClient(
        {
            "status": "success",
            "remarks": "",
            "data": make_payload(),
        }
    )

    adapter = DhanIntradayCandleAdapter(
        client
    )

    candle = adapter.get_one_minute_candle(
        security_id="12345",
        symbol="NIFTY-TEST-CE",
        candle_start=CANDLE_START,
        requested_at=REQUESTED_AT,
    )

    assert candle.close == 105.0


def test_nested_success_envelope_is_supported() -> None:
    client = FakeDhanClient(
        {
            "status": "success",
            "data": {
                "status": "success",
                "data": make_payload(),
            },
        }
    )

    adapter = DhanIntradayCandleAdapter(
        client
    )

    candle = adapter.get_one_minute_candle(
        security_id="12345",
        symbol="NIFTY-TEST-CE",
        candle_start=CANDLE_START,
        requested_at=REQUESTED_AT,
    )

    assert candle.high == 108.0


def test_provider_failure_is_fail_closed() -> None:
    client = FakeDhanClient(
        {
            "status": "failure",
            "remarks": "historical unavailable",
            "data": "",
        }
    )

    adapter = DhanIntradayCandleAdapter(
        client
    )

    with pytest.raises(
        RuntimeError,
        match="historical unavailable",
    ):
        adapter.get_one_minute_candle(
            security_id="12345",
            symbol="NIFTY-TEST-CE",
            candle_start=CANDLE_START,
            requested_at=REQUESTED_AT,
        )


def test_exact_915_timestamp_is_required() -> None:
    client = FakeDhanClient(
        make_payload(
            timestamp=datetime(
                2026,
                8,
                10,
                9,
                16,
            )
        )
    )

    adapter = DhanIntradayCandleAdapter(
        client
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "does not contain the exact "
            "requested candle timestamp"
        ),
    ):
        adapter.get_one_minute_candle(
            security_id="12345",
            symbol="NIFTY-TEST-CE",
            candle_start=CANDLE_START,
            requested_at=REQUESTED_AT,
        )


def test_duplicate_915_timestamp_is_rejected() -> None:
    timestamp = epoch_for(
        CANDLE_START
    )

    payload = {
        "open": [
            100.0,
            101.0,
        ],
        "high": [
            108.0,
            109.0,
        ],
        "low": [
            97.0,
            98.0,
        ],
        "close": [
            105.0,
            106.0,
        ],
        "timestamp": [
            timestamp,
            timestamp,
        ],
    }

    adapter = DhanIntradayCandleAdapter(
        FakeDhanClient(
            payload
        )
    )

    with pytest.raises(
        RuntimeError,
        match="duplicate requested candle timestamps",
    ):
        adapter.get_one_minute_candle(
            security_id="12345",
            symbol="NIFTY-TEST-CE",
            candle_start=CANDLE_START,
            requested_at=REQUESTED_AT,
        )


def test_inconsistent_array_lengths_are_rejected() -> None:
    payload = make_payload()

    payload["close"] = [
        105.0,
        106.0,
    ]

    adapter = DhanIntradayCandleAdapter(
        FakeDhanClient(
            payload
        )
    )

    with pytest.raises(
        RuntimeError,
        match="inconsistent lengths",
    ):
        adapter.get_one_minute_candle(
            security_id="12345",
            symbol="NIFTY-TEST-CE",
            candle_start=CANDLE_START,
            requested_at=REQUESTED_AT,
        )


def test_empty_historical_response_is_rejected() -> None:
    payload = {
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "timestamp": [],
    }

    adapter = DhanIntradayCandleAdapter(
        FakeDhanClient(
            payload
        )
    )

    with pytest.raises(
        RuntimeError,
        match="contains no candles",
    ):
        adapter.get_one_minute_candle(
            security_id="12345",
            symbol="NIFTY-TEST-CE",
            candle_start=CANDLE_START,
            requested_at=REQUESTED_AT,
        )


def test_candle_cannot_be_requested_before_completion() -> None:
    client = FakeDhanClient(
        make_payload()
    )

    adapter = DhanIntradayCandleAdapter(
        client
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "cannot be requested before "
            "candle completion"
        ),
    ):
        adapter.get_one_minute_candle(
            security_id="12345",
            symbol="NIFTY-TEST-CE",
            candle_start=CANDLE_START,
            requested_at=datetime(
                2026,
                8,
                10,
                9,
                15,
                59,
            ),
        )

    assert client.calls == []


def test_request_date_must_match_candle_date() -> None:
    client = FakeDhanClient(
        make_payload()
    )

    adapter = DhanIntradayCandleAdapter(
        client
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "requested_at date must match "
            "candle_start date"
        ),
    ):
        adapter.get_one_minute_candle(
            security_id="12345",
            symbol="NIFTY-TEST-CE",
            candle_start=CANDLE_START,
            requested_at=datetime(
                2026,
                8,
                11,
                9,
                16,
            ),
        )

    assert client.calls == []


def test_invalid_timestamp_is_rejected() -> None:
    payload = make_payload()

    payload["timestamp"] = [
        "not-an-epoch",
    ]

    adapter = DhanIntradayCandleAdapter(
        FakeDhanClient(
            payload
        )
    )

    with pytest.raises(
        RuntimeError,
        match="historical timestamp is invalid",
    ):
        adapter.get_one_minute_candle(
            security_id="12345",
            symbol="NIFTY-TEST-CE",
            candle_start=CANDLE_START,
            requested_at=REQUESTED_AT,
        )


def test_invalid_ohlc_is_rejected() -> None:
    payload = make_payload()

    payload["high"] = [
        90.0,
    ]

    adapter = DhanIntradayCandleAdapter(
        FakeDhanClient(
            payload
        )
    )

    with pytest.raises(
        ValueError,
        match="high cannot be lower than low",
    ):
        adapter.get_one_minute_candle(
            security_id="12345",
            symbol="NIFTY-TEST-CE",
            candle_start=CANDLE_START,
            requested_at=REQUESTED_AT,
        )
