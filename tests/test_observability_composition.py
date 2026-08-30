"""
M14 production observability composition tests.

Composition must reuse exact authoritative subsystem owners and
must not evaluate health or mutate runtime state.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, cast

from src.app.bootstrap import (
    compose_observability_foundation,
)
from src.app.container import (
    PhoenixDhanContainer,
    PhoenixPersistenceContainer,
    PhoenixRuntimeStartupContainer,
    build_dhan_foundation,
    build_notification_foundation,
    build_observability_foundation,
    build_persistence_foundation,
    build_runtime_startup_foundation,
)
from src.broker.dhan_broker import DhanBroker
from src.database.engine import DatabaseConfig
from src.runtime.event_bus import RuntimeEventBus
from src.runtime.recovery_types import (
    BrokerRecoveryOrderSnapshot,
    BrokerRecoveryPositionSnapshot,
)
from src.runtime.runtime_events import RuntimeEventType
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeMode,
    RuntimeState,
)
from src.services.scheduler import TradingDayScheduler


TRADING_DATE = date(2026, 8, 31)
CREATED_AT = datetime(2026, 8, 31, 8, 30)


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
            "observability composition must not query broker orders"
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
            "observability composition must not query broker positions"
        )


class _RecoveryRestorer:
    def restore_order(
        self,
        *,
        persisted_order: object,
        broker_snapshot: BrokerRecoveryOrderSnapshot,
    ) -> None:
        del persisted_order
        del broker_snapshot
        raise AssertionError(
            "observability composition must not restore orders"
        )

    def restore_position(
        self,
        *,
        persisted_position: object,
        broker_snapshot: BrokerRecoveryPositionSnapshot,
    ) -> None:
        del persisted_position
        del broker_snapshot
        raise AssertionError(
            "observability composition must not restore positions"
        )


def _test_dhan_broker() -> DhanBroker:
    broker = object.__new__(DhanBroker)
    broker._client_id = "DHAN-M14-COMPOSITION"
    broker._access_token = "TEST-TOKEN"

    test_broker = cast(Any, broker)
    test_broker._context = object()
    test_broker._client = object()
    return broker


def _build_owners() -> tuple[
    PhoenixPersistenceContainer,
    PhoenixDhanContainer,
    PhoenixRuntimeStartupContainer,
]:
    persistence = build_persistence_foundation(
        config=DatabaseConfig.sqlite_memory()
    )

    dhan = build_dhan_foundation(
        broker=_test_dhan_broker(),
        profile_fetcher=lambda: {
            "dhanClientId": "DHAN-M14-COMPOSITION"
        },
    )

    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    runtime_startup = build_runtime_startup_foundation(
        persistence=persistence,
        scheduler=scheduler,
        broker_provider=_RecoveryBroker(),
        state_restorer=_RecoveryRestorer(),
        runtime_id=RuntimeId("PHOENIX:M14:COMPOSITION"),
        mode=RuntimeMode.DRY_RUN,
        created_at=CREATED_AT,
        event_bus=RuntimeEventBus(),
    )

    return persistence, dhan, runtime_startup


def test_observability_composition_reuses_exact_configured_owners() -> None:
    persistence, dhan, runtime_startup = _build_owners()

    try:
        notification = build_notification_foundation(
            runtime_startup=runtime_startup,
            telegram_enabled=True,
            telegram_bot_token="TEST-BOT-TOKEN",
            telegram_chat_id="TEST-CHAT-ID",
        )

        runtime_health = runtime_startup.health_supervisor
        queue = notification.queued_channel

        assert runtime_health is not None
        assert queue is not None

        health_before = runtime_health.latest_snapshot
        scheduler_before = runtime_startup.scheduler.snapshot
        queue_before = queue.snapshot(captured_at=CREATED_AT)

        subscribers_before = tuple(
            runtime_startup.event_bus.subscriber_count(
                event_type
            )
            for event_type in RuntimeEventType
        )

        observability = compose_observability_foundation(
            persistence=persistence,
            dhan=dhan,
            runtime_startup=runtime_startup,
            notification=notification,
        )

        assert observability.persistence is persistence
        assert observability.dhan is dhan
        assert observability.runtime_startup is runtime_startup
        assert observability.notification is notification
        assert observability.runtime_health is runtime_health
        assert observability.service.runtime_health is runtime_health

        assert (
            observability.account_health_source.repository
            is persistence.account_health_repository
        )
        assert (
            observability.scheduler_source.scheduler
            is runtime_startup.scheduler
        )
        assert (
            observability.event_bus_source.event_bus
            is runtime_startup.event_bus
        )

        assert observability.notification_source is not None
        assert observability.notification_source.queue is queue

        assert observability.service.metric_sources == (
            observability.account_health_source,
            observability.scheduler_source,
            observability.event_bus_source,
            observability.notification_source,
        )

        assert observability.service.diagnostic_sources == (
            observability.account_health_source,
            observability.scheduler_source,
            observability.notification_source,
        )

        assert runtime_health.latest_snapshot is health_before
        assert runtime_startup.scheduler.snapshot == scheduler_before
        assert queue.snapshot(captured_at=CREATED_AT) == queue_before
        assert runtime_startup.orchestrator.state is RuntimeState.CREATED

        assert tuple(
            runtime_startup.event_bus.subscriber_count(
                event_type
            )
            for event_type in RuntimeEventType
        ) == subscribers_before

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_observability_composition_omits_unconfigured_notification() -> None:
    persistence, dhan, runtime_startup = _build_owners()

    try:
        runtime_health = runtime_startup.health_supervisor
        assert runtime_health is not None

        observability = build_observability_foundation(
            persistence=persistence,
            dhan=dhan,
            runtime_startup=runtime_startup,
        )

        assert observability.notification is None
        assert observability.notification_source is None
        assert observability.runtime_health is runtime_health

        assert observability.service.metric_sources == (
            observability.account_health_source,
            observability.scheduler_source,
            observability.event_bus_source,
        )

        assert observability.service.diagnostic_sources == (
            observability.account_health_source,
            observability.scheduler_source,
        )

        assert runtime_health.latest_snapshot is None
        assert runtime_startup.orchestrator.state is RuntimeState.CREATED

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()
