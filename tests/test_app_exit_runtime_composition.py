"""
M10 application composition tests for the durable SELL /
force-exit / EOD dependency graph.
"""

from __future__ import annotations

from datetime import (
    date,
    datetime,
)
from typing import (
    Any,
    cast,
)

from src.app.container import (
    PhoenixExitRuntimeContainer,
    PhoenixTradingRuntimeContainer,
    build_dhan_foundation,
    build_exit_runtime_foundation,
    build_persistence_foundation,
    build_runtime_startup_foundation,
)
from src.app.trading_day_runtime import (
    TradingDayEntryRuntimeCoordinator,
)
from src.broker.dhan_broker import (
    DhanBroker,
)
from src.database.engine import (
    DatabaseConfig,
)
from src.database.exit_durability import (
    DurableExitExecutionProvider,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.runtime.recovery_types import (
    BrokerRecoveryOrderSnapshot,
    BrokerRecoveryPositionSnapshot,
)
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeMode,
)
from src.services.scheduler import (
    TradingDayScheduler,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)

CREATED_AT = datetime(
    2026,
    8,
    10,
    8,
    30,
)


class _RecoveryBroker:
    def get_order_snapshot(
        self,
        *,
        broker_order_id: str,
        checked_at: datetime,
    ) -> BrokerRecoveryOrderSnapshot:
        del broker_order_id
        del checked_at

        raise AssertionError(
            "composition must not query broker"
        )

    def get_position_snapshot(
        self,
        *,
        security_id: str,
        checked_at: datetime,
    ) -> BrokerRecoveryPositionSnapshot:
        del security_id
        del checked_at

        raise AssertionError(
            "composition must not query broker"
        )


class _RecoveryRestorer:
    def restore_order(
        self,
        *,
        persisted_order: object,
        broker_snapshot:
            BrokerRecoveryOrderSnapshot,
    ) -> None:
        del persisted_order
        del broker_snapshot

        raise AssertionError(
            "composition must not restore order"
        )

    def restore_position(
        self,
        *,
        persisted_position: object,
        broker_snapshot:
            BrokerRecoveryPositionSnapshot,
    ) -> None:
        del persisted_position
        del broker_snapshot

        raise AssertionError(
            "composition must not restore position"
        )


def _make_dhan():
    broker = object.__new__(
        DhanBroker
    )

    test_broker = cast(
        Any,
        broker,
    )

    test_broker._client_id = (
        "DHAN-EXIT-COMPOSITION"
    )

    test_broker._access_token = (
        "TEST-TOKEN"
    )

    test_broker._context = object()
    test_broker._client = object()

    return build_dhan_foundation(
        broker=broker,
        profile_fetcher=(
            lambda: {
                "dhanClientId":
                    "DHAN-EXIT-COMPOSITION"
            }
        ),
    )


def test_exit_runtime_preserves_all_shared_owners() -> None:
    persistence = (
        build_persistence_foundation(
            config=(
                DatabaseConfig
                .sqlite_memory()
            )
        )
    )

    try:
        dhan = _make_dhan()

        scheduler = (
            TradingDayScheduler(
                trading_date=TRADING_DATE,
                created_at=CREATED_AT,
            )
        )

        startup = (
            build_runtime_startup_foundation(
                persistence=persistence,
                scheduler=scheduler,
                broker_provider=(
                    _RecoveryBroker()
                ),
                state_restorer=(
                    _RecoveryRestorer()
                ),
                runtime_id=RuntimeId(
                    "EXIT-COMPOSED-RUNTIME"
                ),
                mode=RuntimeMode.LIVE,
                created_at=CREATED_AT,
            )
        )

        registry = PositionRegistry()

        entry_runtime = object.__new__(
            TradingDayEntryRuntimeCoordinator
        )

        trading_runtime = object.__new__(
            PhoenixTradingRuntimeContainer
        )

        object.__setattr__(
            trading_runtime,
            "persistence",
            persistence,
        )

        object.__setattr__(
            trading_runtime,
            "dhan",
            dhan,
        )

        object.__setattr__(
            trading_runtime,
            "runtime_startup",
            startup,
        )

        object.__setattr__(
            trading_runtime,
            "position_registry",
            registry,
        )

        object.__setattr__(
            trading_runtime,
            "entry_runtime",
            entry_runtime,
        )

        exit_runtime = (
            build_exit_runtime_foundation(
                persistence=persistence,
                dhan=dhan,
                trading_runtime=(
                    trading_runtime
                ),
                allow_live_exit_orders=False,
            )
        )

        assert isinstance(
            exit_runtime,
            PhoenixExitRuntimeContainer,
        )

        # --------------------------------------------
        # Root graph identity
        # --------------------------------------------

        assert (
            exit_runtime.persistence
            is persistence
        )

        assert exit_runtime.dhan is dhan

        assert (
            exit_runtime.trading_runtime
            is trading_runtime
        )

        # --------------------------------------------
        # Durable SELL uses shared repositories.
        # --------------------------------------------

        assert (
            exit_runtime
            .exit_persistence
            .order_repository
            is persistence.order_repository
        )

        assert (
            exit_runtime
            .exit_persistence
            .fill_repository
            is persistence.order_fill_repository
        )

        assert (
            exit_runtime
            .exit_persistence
            .position_repository
            is persistence.position_repository
        )

        assert isinstance(
            exit_runtime.durable_exit_provider,
            DurableExitExecutionProvider,
        )

        assert (
            exit_runtime
            .durable_exit_provider
            .delegate
            is dhan.exit_order_adapter
        )

        assert (
            exit_runtime
            .durable_exit_provider
            .persistence
            is exit_runtime.exit_persistence
        )

        # --------------------------------------------
        # One DuplicateOrderGuard across M06 execution
        # and reconciliation.
        # --------------------------------------------

        assert isinstance(
            exit_runtime.duplicate_guard,
            DuplicateOrderGuard,
        )

        assert (
            exit_runtime
            .exit_execution_service
            .duplicate_guard
            is exit_runtime.duplicate_guard
        )

        assert (
            getattr(
                exit_runtime.exit_reconciliation,
                "_duplicate_guard",
            )
            is exit_runtime.duplicate_guard
        )

        assert (
            getattr(
                exit_runtime.exit_reconciliation,
                "_provider",
            )
            is exit_runtime.durable_exit_provider
        )

        # --------------------------------------------
        # Same M07 PositionRegistry.
        # --------------------------------------------

        assert (
            getattr(
                exit_runtime
                .position_lifecycle_manager,
                "_registry",
            )
            is registry
        )

        assert (
            getattr(
                exit_runtime.exit_integration,
                "_registry",
            )
            is registry
        )

        assert (
            getattr(
                exit_runtime.force_exit_coordinator,
                "_registry",
            )
            is registry
        )

        # --------------------------------------------
        # Same M10 scheduler.
        # --------------------------------------------

        assert (
            exit_runtime
            .trading_day_force_exit
            .scheduler
            is scheduler
        )

        assert (
            exit_runtime
            .end_of_day_coordinator
            .scheduler
            is scheduler
        )

        # --------------------------------------------
        # Actual 15:15 runtime shares exact owners.
        # --------------------------------------------

        assert (
            exit_runtime
            .force_exit_runtime
            .trading_day_force_exit
            is exit_runtime.trading_day_force_exit
        )

        assert (
            exit_runtime
            .force_exit_runtime
            .exit_integration
            is exit_runtime.exit_integration
        )

        assert (
            exit_runtime
            .force_exit_runtime
            .exit_reconciliation
            is exit_runtime.exit_reconciliation
        )

        assert (
            exit_runtime
            .force_exit_runtime
            .exit_persistence
            is exit_runtime.exit_persistence
        )

        assert (
            exit_runtime
            .force_exit_runtime
            .durable_exit_provider
            is exit_runtime.durable_exit_provider
        )

        assert (
            exit_runtime
            .force_exit_runtime
            .position_lifecycle_manager
            is exit_runtime
            .position_lifecycle_manager
        )

        assert (
            exit_runtime
            .force_exit_runtime
            .position_registry
            is registry
        )

        assert (
            exit_runtime
            .force_exit_runtime
            .order_repository
            is persistence.order_repository
        )

        assert (
            exit_runtime
            .force_exit_runtime
            .duplicate_guard
            is exit_runtime.duplicate_guard
        )

        assert (
            exit_runtime
            .force_exit_runtime
            .runtime_id
            == "EXIT-COMPOSED-RUNTIME"
        )

        # --------------------------------------------
        # EOD sees durable unresolved BUY + SELL orders.
        # --------------------------------------------

        assert (
            exit_runtime
            .readiness_provider
            .durable_order_repository
            is persistence.order_repository
        )

        assert (
            exit_runtime
            .readiness_provider
            .runtime_id
            == "EXIT-COMPOSED-RUNTIME"
        )

        assert (
            exit_runtime
            .readiness_provider
            .entry_runtime
            is entry_runtime
        )

        assert (
            exit_runtime
            .readiness_provider
            .account_adapter
            is dhan.account_adapter
        )

        # --------------------------------------------
        # LIVE SELL stays explicitly disabled unless
        # production launch opts in.
        # --------------------------------------------

        assert (
            exit_runtime
            .exit_execution_service
            .allow_live_exit_orders
            is False
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_persistence_foundation_owns_fill_repository() -> None:
    persistence = (
        build_persistence_foundation(
            config=(
                DatabaseConfig
                .sqlite_memory()
            )
        )
    )

    try:
        assert (
            persistence
            .order_fill_repository
            .list_by_order(
                "DOES-NOT-EXIST"
            )
            == ()
        )

        assert (
            getattr(
                persistence.order_fill_repository,
                "_sessions",
                persistence.sessions,
            )
            is persistence.sessions
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()
