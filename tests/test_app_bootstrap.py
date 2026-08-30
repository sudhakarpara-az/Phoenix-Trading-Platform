"""
Tests for Phoenix application bootstrap composition.
"""

from datetime import date, datetime
from typing import (
    Any,
    cast,
)

from src.account.dhan_account_adapter import (
    DhanAccountAdapter,
)
from src.app.bootstrap import (
    compose_dhan_foundation,
    compose_persistence_foundation,
    compose_runtime_startup_foundation,
    compose_trading_day_end_of_day,
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
from src.runtime.event_bus import (
    RuntimeEventBus,
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


def test_bootstrap_composes_persistence_foundation():
    persistence = (
        compose_persistence_foundation(
            config=DatabaseConfig.sqlite_memory()
        )
    )

    try:
        assert persistence.database.started is True
        assert persistence.sessions.started is True

        assert (
            persistence.runtime_repository
            .latest()
            is None
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()




def test_bootstrap_composes_shared_dhan_graph():
    broker = object.__new__(
        DhanBroker
    )

    broker._client_id = (
        "DHAN-BOOTSTRAP-001"
    )

    broker._access_token = (
        "TEST-TOKEN"
    )

    test_broker = cast(
        Any,
        broker,
    )

    test_broker._context = object()
    test_broker._client = object()

    dhan = compose_dhan_foundation(
        broker=broker,
        profile_fetcher=(
            lambda: {
                "dhanClientId":
                    "DHAN-BOOTSTRAP-001"
            }
        ),
    )

    assert dhan.broker is broker

    assert (
        dhan.client
        is broker.get_client()
    )

    assert (
        dhan.account_id.value
        == "DHAN-BOOTSTRAP-001"
    )


class _BootstrapRecoveryBroker:
    def get_order_snapshot(
        self,
        *,
        broker_order_id: str,
        checked_at: datetime,
    ) -> BrokerRecoveryOrderSnapshot:
        del broker_order_id
        del checked_at
        raise AssertionError(
            "bootstrap composition must not query broker"
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
            "bootstrap composition must not query broker"
        )


class _BootstrapRecoveryRestorer:
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
            "bootstrap composition must not restore"
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
            "bootstrap composition must not restore"
        )


def test_bootstrap_composes_runtime_startup_foundation():
    persistence = (
        compose_persistence_foundation(
            config=DatabaseConfig.sqlite_memory()
        )
    )

    try:
        scheduler = TradingDayScheduler(
            trading_date=TRADING_DATE,
            created_at=CREATED_AT,
        )

        event_bus = RuntimeEventBus()

        startup = (
            compose_runtime_startup_foundation(
                persistence=persistence,
                scheduler=scheduler,
                broker_provider=(
                    _BootstrapRecoveryBroker()
                ),
                state_restorer=(
                    _BootstrapRecoveryRestorer()
                ),
                runtime_id=RuntimeId(
                    "BOOTSTRAP-RUNTIME"
                ),
                mode=RuntimeMode.DRY_RUN,
                created_at=CREATED_AT,
                event_bus=event_bus,
            )
        )

        assert (
            startup.persistence
            is persistence
        )

        assert (
            startup.scheduler
            is scheduler
        )

        assert (
            startup.event_bus
            is event_bus
        )

        assert (
            startup.recovery_plan
            .recovery_required
            is False
        )

        assert (
            startup.orchestrator
            .recovery_required
            is False
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_bootstrap_preserves_end_of_day_graph() -> None:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    entry_runtime = object.__new__(
        TradingDayEntryRuntimeCoordinator
    )

    account_adapter = object.__new__(
        DhanAccountAdapter
    )

    (
        readiness_provider,
        end_of_day_coordinator,
    ) = compose_trading_day_end_of_day(
        scheduler=scheduler,
        entry_runtime=entry_runtime,
        account_adapter=account_adapter,
    )

    assert (
        readiness_provider.entry_runtime
        is entry_runtime
    )

    assert (
        readiness_provider.account_adapter
        is account_adapter
    )

    assert (
        end_of_day_coordinator.scheduler
        is scheduler
    )


def test_bootstrap_public_exports() -> None:
    from src.app import bootstrap

    assert bootstrap.__all__ == [
        "compose_dhan_foundation",
        "compose_exit_runtime_foundation",
        "compose_persistence_foundation",
        "compose_runtime_startup_foundation",
        "compose_trading_day_end_of_day",
        "compose_trading_runtime_foundation",
        "compose_dhan_recovery_provider",
        "compose_recovery_state_restorer_binding",
        "compose_recovery_foundation",
        "compose_notification_foundation",
        "compose_notification_end_of_day",
        "compose_reporting_foundation",
        "compose_reporting_end_of_day",
        "compose_operator_api_foundation",
        "compose_operator_http_foundation",
        "compose_observability_foundation",
    ]
