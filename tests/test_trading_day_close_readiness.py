"""
M10-T14 application close-readiness provider tests.

No live Dhan request is made.
"""

from datetime import datetime
from typing import Any, cast

import pytest

from src.account.account_types import (
    BrokerAccountId,
)
from src.account.dhan_account_adapter import (
    DhanAccountAdapter,
)
from src.app.trading_day_runtime import (
    TradingDayCloseReadinessProvider,
    TradingDayEntryRuntimeCoordinator,
)
from src.services.scheduler import (
    TradingDayCloseReadiness,
)


NOW = datetime(
    2026,
    8,
    10,
    15,
    20,
)

ACCOUNT_ID = BrokerAccountId(
    "1100003626"
)


class StubPositionRegistry:
    def __init__(
        self,
        open_count: int = 0,
    ) -> None:
        self.open_count = open_count
        self.calls = 0

    def open_positions(
        self,
    ):
        self.calls += 1

        return tuple(
            object()
            for _ in range(
                self.open_count
            )
        )


class StubEntryRuntime(
    TradingDayEntryRuntimeCoordinator
):
    def __init__(
        self,
        *,
        open_positions: int = 0,
        pending_count: int = 0,
    ) -> None:
        self.registry = (
            StubPositionRegistry(
                open_positions
            )
        )

        self.stub_pending_count = (
            pending_count
        )

    @property
    def position_registry(
        self,
    ) -> Any:
        return self.registry

    @property
    def pending_count(
        self,
    ) -> int:
        return self.stub_pending_count


class StubDhanAccountAdapter(
    DhanAccountAdapter
):
    def __init__(
        self,
        *,
        open_positions: int = 0,
        unresolved_orders: int = 0,
    ) -> None:
        self.stub_open_positions = (
            open_positions
        )

        self.stub_unresolved_orders = (
            unresolved_orders
        )

        self.position_calls = []
        self.order_calls = []

        super().__init__(
            dhan_client=object(),
            profile_fetcher=lambda: {},
            account_id=ACCOUNT_ID,
        )

    def fetch_open_position_count(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ) -> int:
        self.position_calls.append(
            (
                broker,
                account_id,
                requested_at,
            )
        )

        return self.stub_open_positions

    def fetch_unresolved_order_count(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ) -> int:
        self.order_calls.append(
            (
                broker,
                account_id,
                requested_at,
            )
        )

        return self.stub_unresolved_orders


def make_provider(
    *,
    local_positions: int = 0,
    local_orders: int = 0,
    broker_positions: int = 0,
    broker_orders: int = 0,
):
    runtime = StubEntryRuntime(
        open_positions=(
            local_positions
        ),
        pending_count=(
            local_orders
        ),
    )

    account = StubDhanAccountAdapter(
        open_positions=(
            broker_positions
        ),
        unresolved_orders=(
            broker_orders
        ),
    )

    provider = (
        TradingDayCloseReadinessProvider(
            entry_runtime=runtime,
            account_adapter=account,
        )
    )

    return (
        provider,
        runtime,
        account,
    )


def test_constructor_preserves_exact_dependencies():
    provider, runtime, account = (
        make_provider()
    )

    assert (
        provider.entry_runtime
        is runtime
    )

    assert (
        provider.account_adapter
        is account
    )


def test_invalid_entry_runtime_rejected():
    _, _, account = make_provider()

    with pytest.raises(
        TypeError,
        match=(
            "TradingDayEntryRuntimeCoordinator"
        ),
    ):
        TradingDayCloseReadinessProvider(
            entry_runtime=cast(
                TradingDayEntryRuntimeCoordinator,
                object(),
            ),
            account_adapter=account,
        )


def test_invalid_account_adapter_rejected():
    _, runtime, _ = make_provider()

    with pytest.raises(
        TypeError,
        match="DhanAccountAdapter",
    ):
        TradingDayCloseReadinessProvider(
            entry_runtime=runtime,
            account_adapter=cast(
                DhanAccountAdapter,
                object(),
            ),
        )


def test_all_zero_is_ready():
    provider, runtime, account = (
        make_provider()
    )

    result = (
        provider.evaluate_close_readiness(
            evaluated_at=NOW,
        )
    )

    assert isinstance(
        result,
        TradingDayCloseReadiness,
    )

    assert result.is_ready is True
    assert result.open_position_count == 0
    assert result.unresolved_order_count == 0

    assert runtime.registry.calls == 1
    assert len(account.position_calls) == 1
    assert len(account.order_calls) == 1


@pytest.mark.parametrize(
    (
        "local_positions",
        "broker_positions",
        "expected",
    ),
    [
        (1, 0, 1),
        (0, 1, 1),
        (1, 1, 1),
        (2, 5, 5),
        (5, 2, 5),
    ],
)
def test_open_position_count_uses_conservative_max(
    local_positions,
    broker_positions,
    expected,
):
    provider, _, _ = make_provider(
        local_positions=(
            local_positions
        ),
        broker_positions=(
            broker_positions
        ),
    )

    result = (
        provider.evaluate_close_readiness(
            evaluated_at=NOW,
        )
    )

    assert (
        result.open_position_count
        == expected
    )

    assert result.is_ready is False


@pytest.mark.parametrize(
    (
        "local_orders",
        "broker_orders",
        "expected",
    ),
    [
        (1, 0, 1),
        (0, 1, 1),
        (1, 1, 1),
        (2, 4, 4),
        (4, 2, 4),
    ],
)
def test_unresolved_order_count_uses_conservative_max(
    local_orders,
    broker_orders,
    expected,
):
    provider, _, _ = make_provider(
        local_orders=(
            local_orders
        ),
        broker_orders=(
            broker_orders
        ),
    )

    result = (
        provider.evaluate_close_readiness(
            evaluated_at=NOW,
        )
    )

    assert (
        result.unresolved_order_count
        == expected
    )

    assert result.is_ready is False


def test_broker_queries_use_adapter_identity_and_timestamp():
    provider, _, account = (
        make_provider()
    )

    provider.evaluate_close_readiness(
        evaluated_at=NOW,
    )

    assert account.position_calls == [
        (
            account.broker,
            account.account_id,
            NOW,
        )
    ]

    assert account.order_calls == [
        (
            account.broker,
            account.account_id,
            NOW,
        )
    ]


def test_non_datetime_rejected_before_inspection():
    provider, runtime, account = (
        make_provider()
    )

    with pytest.raises(
        TypeError,
        match=(
            "evaluated_at must be a datetime"
        ),
    ):
        provider.evaluate_close_readiness(
            evaluated_at=cast(
                datetime,
                None,
            ),
        )

    assert runtime.registry.calls == 0
    assert account.position_calls == []
    assert account.order_calls == []


def test_broker_position_failure_propagates():
    class ExplodingAccount(
        StubDhanAccountAdapter
    ):
        def fetch_open_position_count(
            self,
            *,
            broker,
            account_id,
            requested_at,
        ):
            del (
                broker,
                account_id,
                requested_at,
            )

            raise RuntimeError(
                "broker positions unavailable"
            )

    runtime = StubEntryRuntime()

    provider = (
        TradingDayCloseReadinessProvider(
            entry_runtime=runtime,
            account_adapter=(
                ExplodingAccount()
            ),
        )
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "broker positions unavailable"
        ),
    ):
        provider.evaluate_close_readiness(
            evaluated_at=NOW,
        )


def test_broker_order_failure_propagates():
    class ExplodingAccount(
        StubDhanAccountAdapter
    ):
        def fetch_unresolved_order_count(
            self,
            *,
            broker,
            account_id,
            requested_at,
        ):
            del (
                broker,
                account_id,
                requested_at,
            )

            raise RuntimeError(
                "broker orders unavailable"
            )

    runtime = StubEntryRuntime()

    provider = (
        TradingDayCloseReadinessProvider(
            entry_runtime=runtime,
            account_adapter=(
                ExplodingAccount()
            ),
        )
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "broker orders unavailable"
        ),
    ):
        provider.evaluate_close_readiness(
            evaluated_at=NOW,
        )


@pytest.mark.parametrize(
    (
        "attribute",
        "value",
        "message",
    ),
    [
        (
            "stub_open_positions",
            -1,
            "broker open position count",
        ),
        (
            "stub_unresolved_orders",
            True,
            "broker unresolved order count",
        ),
    ],
)
def test_invalid_broker_counts_fail_closed(
    attribute,
    value,
    message,
):
    provider, _, account = (
        make_provider()
    )

    setattr(
        account,
        attribute,
        value,
    )

    with pytest.raises(
        RuntimeError,
        match=message,
    ):
        provider.evaluate_close_readiness(
            evaluated_at=NOW,
        )


def test_public_export():
    import src.app.trading_day_runtime as runtime

    assert (
        runtime.TradingDayCloseReadinessProvider
        is TradingDayCloseReadinessProvider
    )
