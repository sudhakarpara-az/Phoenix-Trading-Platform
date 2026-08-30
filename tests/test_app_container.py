"""
Tests for Phoenix application composition boundaries.
"""

from datetime import date, datetime
from typing import (
    Any,
    cast,
)

from src.account.dhan_account_adapter import (
    DhanAccountAdapter,
)
from src.app.container import (
    PhoenixDhanContainer,
    PhoenixPersistenceContainer,
    PhoenixRuntimeStartupContainer,
    build_dhan_foundation,
    build_persistence_foundation,
    build_runtime_startup_foundation,
    build_trading_day_end_of_day,
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
from src.database.schema import (
    RuntimeSessionRecord,
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
    RuntimeState,
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


def test_persistence_foundation_uses_one_shared_session_manager():
    persistence = (
        build_persistence_foundation(
            config=DatabaseConfig.sqlite_memory()
        )
    )

    try:
        assert isinstance(
            persistence,
            PhoenixPersistenceContainer,
        )

        assert persistence.database.started is True
        assert persistence.sessions.started is True

        repositories = (
            persistence.runtime_repository,
            persistence.signal_repository,
            persistence.option_selection_repository,
            persistence.order_repository,
            persistence.position_repository,
            persistence.audit_repository,
            persistence.broker_account_repository,
            persistence.broker_session_repository,
            persistence.account_fund_repository,
            persistence.broker_connectivity_repository,
            persistence.account_health_repository,
            persistence.account_eligibility_repository,
        )

        for repository in repositories:
            assert (
                repository._sessions
                is persistence.sessions
            )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_persistence_foundation_schema_is_queryable():
    persistence = (
        build_persistence_foundation(
            config=DatabaseConfig.sqlite_memory()
        )
    )

    try:
        assert (
            persistence.runtime_repository.latest()
            is None
        )

        assert (
            persistence.order_repository
            .list_open_orders(
                "NON-EXISTENT-RUNTIME"
            )
            == ()
        )

        assert (
            persistence.position_repository
            .list_open_positions(
                "NON-EXISTENT-RUNTIME"
            )
            == ()
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()




def _test_dhan_broker():
    broker = object.__new__(
        DhanBroker
    )

    broker._client_id = (
        "DHAN-COMPOSITION-001"
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

    return broker


def test_dhan_foundation_shares_one_client():
    broker = _test_dhan_broker()

    profile_fetcher = (
        lambda: {
            "dhanClientId":
                "DHAN-COMPOSITION-001"
        }
    )

    dhan = build_dhan_foundation(
        broker=broker,
        profile_fetcher=profile_fetcher,
    )

    assert isinstance(
        dhan,
        PhoenixDhanContainer,
    )

    assert dhan.broker is broker

    assert (
        dhan.client
        is broker.get_client()
    )

    assert (
        dhan.account_id.value
        == "DHAN-COMPOSITION-001"
    )

    assert (
        getattr(
            dhan.order_adapter,
            "_dhan",
        )
        is dhan.client
    )

    assert (
        getattr(
            dhan.exit_order_adapter,
            "_dhan",
        )
        is dhan.client
    )

    assert (
        getattr(
            dhan.account_adapter,
            "_dhan_client",
        )
        is dhan.client
    )

    assert (
        dhan.account_adapter.account_id
        is dhan.account_id
    )


def test_dhan_foundation_rejects_invalid_profile_fetcher():
    broker = _test_dhan_broker()

    try:
        build_dhan_foundation(
            broker=broker,
            profile_fetcher=cast(
                Any,
                None,
            ),
        )

    except TypeError as exc:
        assert (
            str(exc)
            == "profile_fetcher must be callable"
        )

    else:
        raise AssertionError(
            "invalid profile_fetcher accepted"
        )


def test_dhan_foundation_rejects_missing_client():
    broker = _test_dhan_broker()

    cast(
        Any,
        broker,
    )._client = None

    try:
        build_dhan_foundation(
            broker=broker,
            profile_fetcher=lambda: {},
        )

    except RuntimeError as exc:
        assert (
            str(exc)
            == (
                "DhanBroker returned no "
                "authenticated client"
            )
        )

    else:
        raise AssertionError(
            "missing Dhan client accepted"
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
            "clean startup must not query broker orders"
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
            "clean startup must not query broker positions"
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
            "clean startup must not restore orders"
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
            "clean startup must not restore positions"
        )


def test_runtime_startup_foundation_preserves_shared_graph():
    persistence = (
        build_persistence_foundation(
            config=DatabaseConfig.sqlite_memory()
        )
    )

    try:
        scheduler = TradingDayScheduler(
            trading_date=TRADING_DATE,
            created_at=CREATED_AT,
        )

        event_bus = RuntimeEventBus()

        runtime_id = RuntimeId(
            "PHOENIX:2026-08-10:COMPOSITION"
        )

        startup = (
            build_runtime_startup_foundation(
                persistence=persistence,
                scheduler=scheduler,
                broker_provider=_RecoveryBroker(),
                state_restorer=_RecoveryRestorer(),
                runtime_id=runtime_id,
                mode=RuntimeMode.DRY_RUN,
                created_at=CREATED_AT,
                event_bus=event_bus,
            )
        )

        assert isinstance(
            startup,
            PhoenixRuntimeStartupContainer,
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
            startup.recovery_service
            ._runtime_repository
            is persistence.runtime_repository
        )

        assert (
            startup.recovery_service
            ._order_repository
            is persistence.order_repository
        )

        assert (
            startup.recovery_service
            ._position_repository
            is persistence.position_repository
        )

        assert (
            startup.startup_coordinator
            .scheduler
            is scheduler
        )

        assert (
            startup.startup_coordinator
            ._recovery_service
            is startup.recovery_service
        )

        assert (
            startup.recovery_plan
            .recovery_required
            is False
        )

        assert (
            startup.orchestrator.state
            is RuntimeState.CREATED
        )

        assert (
            startup.orchestrator.runtime_id
            == runtime_id
        )

        assert (
            startup.orchestrator.mode
            is RuntimeMode.DRY_RUN
        )

        assert (
            startup.orchestrator
            .recovery_required
            is False
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_interrupted_runtime_sets_orchestrator_recovery_required():
    persistence = (
        build_persistence_foundation(
            config=DatabaseConfig.sqlite_memory()
        )
    )

    try:
        persistence.runtime_repository.add(
            RuntimeSessionRecord(
                runtime_id="PREVIOUS-RUNTIME",
                trading_date=TRADING_DATE,
                mode="DRY_RUN",
                state="RUNNING",
                started_at=CREATED_AT,
                updated_at=CREATED_AT,
                recovery_required=False,
                recovered=False,
            )
        )

        scheduler = TradingDayScheduler(
            trading_date=TRADING_DATE,
            created_at=CREATED_AT,
        )

        startup = (
            build_runtime_startup_foundation(
                persistence=persistence,
                scheduler=scheduler,
                broker_provider=_RecoveryBroker(),
                state_restorer=_RecoveryRestorer(),
                runtime_id=RuntimeId(
                    "CURRENT-RUNTIME"
                ),
                mode=RuntimeMode.DRY_RUN,
                created_at=CREATED_AT,
            )
        )

        assert (
            startup.recovery_plan
            .source_runtime_id
            == "PREVIOUS-RUNTIME"
        )

        assert (
            startup.recovery_plan
            .recovery_required
            is True
        )

        assert (
            startup.orchestrator
            .recovery_required
            is True
        )

        assert (
            startup.orchestrator.state
            is RuntimeState.CREATED
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_end_of_day_composition_preserves_instances() -> None:
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
    ) = build_trading_day_end_of_day(
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

    assert (
        end_of_day_coordinator
        ._readiness_provider
        is readiness_provider
    )


def test_container_public_exports() -> None:
    from src.app import container

    assert container.__all__ == [
        "PhoenixDhanContainer",
        "PhoenixExitRuntimeContainer",
        "PhoenixPersistenceContainer",
        "PhoenixRuntimeStartupContainer",
        "PhoenixTradingRuntimeContainer",
        "build_dhan_foundation",
        "build_exit_runtime_foundation",
        "build_persistence_foundation",
        "build_runtime_startup_foundation",
        "build_trading_day_end_of_day",
        "build_trading_runtime_foundation",
        "build_dhan_recovery_provider",
        "build_recovery_state_restorer_binding",
        "build_recovery_foundation",
        "PhoenixNotificationContainer",
        "build_notification_foundation",
        "build_notification_end_of_day",
        "PhoenixReportingContainer",
        "build_reporting_foundation",
        "build_reporting_end_of_day",
        "PhoenixOperatorApiContainer",
        "build_operator_api_foundation",
        "PhoenixOperatorHttpContainer",
        "build_operator_http_foundation",
        "PhoenixObservabilityContainer",
        "build_observability_foundation",
    ]
