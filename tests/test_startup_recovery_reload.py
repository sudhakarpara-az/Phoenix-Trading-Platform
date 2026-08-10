
"""
M10 startup recovery ordering regression.

Order restoration may change durable position exposure.
Position reconciliation must therefore reload PositionRecord
state only after all unresolved order restores have completed.
"""

from types import SimpleNamespace
from typing import (
    Any,
    cast,
)

from src.runtime.recovery_types import (
    BrokerRecoveryOrderSnapshot,
    BrokerRecoveryOrderState,
)
from src.runtime.startup_recovery_service import (
    StartupRecoveryService,
)

from tests.test_startup_recovery_service import (
    NOW,
    make_orchestrator,
)


class RuntimeRepository:
    def latest_for_trading_date(
        self,
        trading_date,
    ):
        del trading_date
        return None


class OrderRepository:
    def __init__(
        self,
    ) -> None:
        self.order = SimpleNamespace(
            order_intent_id=(
                "EXIT-20260810-000003"
            ),
            broker_order_id=(
                "BROKER-SELL-003"
            ),
        )

    def list_open_orders(
        self,
        runtime_id,
    ):
        del runtime_id
        return (
            self.order,
        )


class MutablePositionRepository:
    def __init__(
        self,
    ) -> None:
        self.calls = 0

        self.positions: tuple[
            Any,
            ...,
        ] = (
            SimpleNamespace(
                position_id="POS-001",
                security_id="41009",
                open_quantity=65,
            ),
        )

    def list_open_positions(
        self,
        runtime_id,
    ):
        del runtime_id

        self.calls += 1

        return self.positions


class Broker:
    def __init__(
        self,
    ) -> None:
        self.order_calls = 0
        self.position_calls = 0

    def get_order_snapshot(
        self,
        *,
        broker_order_id,
        checked_at,
    ):
        self.order_calls += 1

        return BrokerRecoveryOrderSnapshot(
            broker_order_id=(
                broker_order_id
            ),
            state=(
                BrokerRecoveryOrderState
                .FILLED
            ),
            quantity=65,
            filled_quantity=65,
            average_fill_price=110.0,
            checked_at=checked_at,
        )

    def get_position_snapshot(
        self,
        *,
        security_id,
        checked_at,
    ):
        del security_id
        del checked_at

        self.position_calls += 1

        raise AssertionError(
            "closed durable exposure must not "
            "be reconciled from stale position state"
        )


class ClearingRestorer:
    def __init__(
        self,
        position_repository:
            MutablePositionRepository,
    ) -> None:
        self.position_repository = (
            position_repository
        )

        self.order_calls = 0
        self.position_calls = 0

    def restore_order(
        self,
        *,
        persisted_order,
        broker_snapshot,
    ) -> None:
        del persisted_order
        del broker_snapshot

        self.order_calls += 1

        # Simulates a recovered FILLED SELL whose restoration
        # durably closes the PositionRecord.
        self.position_repository.positions = ()

    def restore_position(
        self,
        *,
        persisted_position,
        broker_snapshot,
    ) -> None:
        del persisted_position
        del broker_snapshot

        self.position_calls += 1

        raise AssertionError(
            "closed position must not be restored"
        )


def test_positions_are_reloaded_after_order_restore():
    position_repository = (
        MutablePositionRepository()
    )

    broker = Broker()

    restorer = ClearingRestorer(
        position_repository
    )

    service = StartupRecoveryService(
        runtime_repository=(
            RuntimeRepository()
        ),
        order_repository=cast(
            Any,
            OrderRepository(),
        ),
        position_repository=cast(
            Any,
            position_repository,
        ),
        broker_provider=broker,
        state_restorer=restorer,
    )

    orchestrator = (
        make_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id=(
            "OLD-RUNTIME"
        ),
        checked_at=NOW,
    )

    assert result.completed is True
    assert result.issue_count == 0

    assert (
        result.recovered_orders
        == 1
    )

    assert (
        result.recovered_positions
        == 0
    )

    assert restorer.order_calls == 1
    assert restorer.position_calls == 0

    # recover() must load position exposure only after the
    # order restore has changed durable state.
    assert (
        position_repository.calls
        == 1
    )

    assert broker.order_calls == 1
    assert broker.position_calls == 0
