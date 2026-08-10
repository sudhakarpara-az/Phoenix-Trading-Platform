"""
M10-T14 direct raw-market ingress integration tests.
"""

from datetime import datetime

import pytest

from src.app.trading_day_runtime import (
    TradingDayMarketIngressError,
    TradingDayMarketIngressHandler,
    TradingDayTickRuntimeCoordinator,
    TradingDayTickRuntimeResult,
)
from src.market.market_types import (
    Exchange,
    MarketTick,
    TickType,
)
from src.market.message_dispatcher import (
    MessageDispatcher,
)
from src.market.tick_processor import (
    TickProcessor,
)


NOW = datetime(
    2026,
    8,
    10,
    9,
    21,
    1,
)


def make_tick() -> MarketTick:
    return MarketTick(
        exchange=next(iter(Exchange)),
        symbol="NIFTY-TEST",
        security_id="100001",
        ltp=100.0,
        volume=1,
        timestamp=NOW,
        tick_type=next(iter(TickType)),
    )


class StubTickProcessor(
    TickProcessor
):
    def __init__(
        self,
        *,
        result=None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.messages = []

    def process(
        self,
        message,
    ):
        self.messages.append(
            message
        )

        if self.error is not None:
            raise self.error

        return self.result


class StubTickRuntime(
    TradingDayTickRuntimeCoordinator
):
    def __init__(
        self,
        *,
        result=None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls = []

    def process_tick(
        self,
        tick,
        *,
        dry_run,
    ):
        self.calls.append(
            (
                tick,
                dry_run,
            )
        )

        if self.error is not None:
            raise self.error

        if self.result is not None:
            return self.result

        return TradingDayTickRuntimeResult(
            tick=tick,
            events=(),
            selected_event=None,
            signal_runtime_result=None,
            entry_runtime_result=None,
        )


def test_constructor_preserves_dependencies() -> None:
    processor = StubTickProcessor()
    runtime = StubTickRuntime()

    handler = TradingDayMarketIngressHandler(
        tick_processor=processor,
        tick_runtime=runtime,
        dry_run=True,
    )

    assert handler.tick_processor is processor
    assert handler.tick_runtime is runtime
    assert handler.dry_run is True


def test_invalid_tick_processor_rejected() -> None:
    with pytest.raises(
        TypeError,
        match=(
            "tick_processor must be a TickProcessor"
        ),
    ):
        TradingDayMarketIngressHandler(
            tick_processor=object(),
            tick_runtime=StubTickRuntime(),
            dry_run=True,
        )


def test_invalid_tick_runtime_rejected() -> None:
    with pytest.raises(
        TypeError,
        match=(
            "tick_runtime must be a "
            "TradingDayTickRuntimeCoordinator"
        ),
    ):
        TradingDayMarketIngressHandler(
            tick_processor=StubTickProcessor(),
            tick_runtime=object(),
            dry_run=True,
        )


def test_non_bool_dry_run_rejected() -> None:
    with pytest.raises(
        TypeError,
        match="dry_run must be bool",
    ):
        TradingDayMarketIngressHandler(
            tick_processor=StubTickProcessor(),
            tick_runtime=StubTickRuntime(),
            dry_run=1,
        )


def test_non_tick_message_stops_after_processor() -> None:
    processor = StubTickProcessor(
        result=None
    )

    runtime = StubTickRuntime()

    handler = TradingDayMarketIngressHandler(
        tick_processor=processor,
        tick_runtime=runtime,
        dry_run=True,
    )

    raw = {
        "type": "control"
    }

    result = handler(
        raw
    )

    assert result is None

    assert processor.messages == [
        raw
    ]

    assert runtime.calls == []


@pytest.mark.parametrize(
    "dry_run",
    [
        True,
        False,
    ],
)
def test_normalized_tick_is_forwarded_once(
    dry_run,
) -> None:
    tick = make_tick()

    processor = StubTickProcessor(
        result=tick
    )

    runtime = StubTickRuntime()

    handler = TradingDayMarketIngressHandler(
        tick_processor=processor,
        tick_runtime=runtime,
        dry_run=dry_run,
    )

    raw = {
        "security_id": tick.security_id,
        "LTP": tick.ltp,
    }

    result = handler(
        raw
    )

    assert result is None

    assert processor.messages == [
        raw
    ]

    assert runtime.calls == [
        (
            tick,
            dry_run,
        )
    ]


def test_handler_is_directly_compatible_with_dispatcher() -> None:
    tick = make_tick()

    processor = StubTickProcessor(
        result=tick
    )

    runtime = StubTickRuntime()

    handler = TradingDayMarketIngressHandler(
        tick_processor=processor,
        tick_runtime=runtime,
        dry_run=True,
    )

    dispatcher = MessageDispatcher()

    dispatcher.register(
        handler
    )

    assert dispatcher.count() == 1

    raw = {
        "security_id": tick.security_id
    }

    dispatcher.dispatch(
        raw
    )

    assert processor.messages == [
        raw
    ]

    assert runtime.calls == [
        (
            tick,
            True,
        )
    ]


def test_invalid_processor_result_fails_closed() -> None:
    processor = StubTickProcessor(
        result="not-a-market-tick"
    )

    handler = TradingDayMarketIngressHandler(
        tick_processor=processor,
        tick_runtime=StubTickRuntime(),
        dry_run=True,
    )

    with pytest.raises(
        TradingDayMarketIngressError,
        match=(
            "TickProcessor returned invalid "
            "market tick result"
        ),
    ):
        handler(
            {"raw": "message"}
        )


def test_invalid_runtime_result_fails_closed() -> None:
    tick = make_tick()

    handler = TradingDayMarketIngressHandler(
        tick_processor=StubTickProcessor(
            result=tick
        ),
        tick_runtime=StubTickRuntime(
            result="invalid-runtime-result"
        ),
        dry_run=True,
    )

    with pytest.raises(
        TradingDayMarketIngressError,
        match=(
            "tick runtime returned invalid result"
        ),
    ):
        handler(
            {"raw": "message"}
        )


def test_processor_exception_propagates() -> None:
    failure = RuntimeError(
        "processor failed"
    )

    handler = TradingDayMarketIngressHandler(
        tick_processor=StubTickProcessor(
            error=failure
        ),
        tick_runtime=StubTickRuntime(),
        dry_run=True,
    )

    with pytest.raises(
        RuntimeError,
        match="processor failed",
    ):
        handler(
            {"raw": "message"}
        )


def test_tick_runtime_exception_propagates() -> None:
    tick = make_tick()

    failure = RuntimeError(
        "runtime failed"
    )

    handler = TradingDayMarketIngressHandler(
        tick_processor=StubTickProcessor(
            result=tick
        ),
        tick_runtime=StubTickRuntime(
            error=failure
        ),
        dry_run=False,
    )

    with pytest.raises(
        RuntimeError,
        match="runtime failed",
    ):
        handler(
            {"raw": "message"}
        )


def test_market_ingress_contract_is_public() -> None:
    import src.app.trading_day_runtime as runtime

    assert (
        "TradingDayMarketIngressHandler"
        in runtime.__all__
    )

    assert (
        "TradingDayMarketIngressError"
        in runtime.__all__
    )
