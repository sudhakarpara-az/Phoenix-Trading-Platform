

"""
M13 production composition tests.

M13 must reuse the exact owners already created by M07/M08/M12.
"""

from __future__ import annotations

from datetime import (
    date,
    datetime,
)
from types import SimpleNamespace

import pytest

from src.app.bootstrap import (
    compose_operator_api_foundation,
)
from src.app.container import (
    PhoenixExitRuntimeContainer,
    PhoenixOperatorApiContainer,
    PhoenixRuntimeStartupContainer,
    PhoenixTradingRuntimeContainer,
    build_operator_api_foundation,
    build_persistence_foundation,
    build_reporting_foundation,
    PhoenixNotificationContainer,
)
from src.database.engine import (
    DatabaseConfig,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.runtime_orchestrator import (
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeMode,
)
from src.services.scheduler import (
    TradingDayScheduler,
)

def _operator_exit_runtime(
    trading_runtime: PhoenixTradingRuntimeContainer,
) -> PhoenixExitRuntimeContainer:
    exit_runtime = object.__new__(
        PhoenixExitRuntimeContainer
    )

    object.__setattr__(
        exit_runtime,
        "persistence",
        trading_runtime.persistence,
    )

    object.__setattr__(
        exit_runtime,
        "trading_runtime",
        trading_runtime,
    )

    command_owner = type(
        "_OperatorControlCommands",
        (),
        {},
    )()

    object.__setattr__(
        command_owner,
        "trading_control",
        trading_runtime.trading_control,
    )

    object.__setattr__(
        exit_runtime,
        "trading_control_commands",
        command_owner,
    )

    return exit_runtime


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



class _FakeSummaryCollector:
    def snapshot(
        self,
        *,
        captured_at,
    ):
        raise AssertionError(
            "composition must not capture notifications"
        )


class _FakeQueuedChannel:
    def snapshot(
        self,
        *,
        captured_at,
    ):
        raise AssertionError(
            "composition must not capture queue state"
        )


def _operator_notification_container(
    runtime_startup,
):
    notification = object.__new__(
        PhoenixNotificationContainer
    )

    object.__setattr__(
        notification,
        "runtime_startup",
        runtime_startup,
    )

    object.__setattr__(
        notification,
        "summary_collector",
        _FakeSummaryCollector(),
    )

    object.__setattr__(
        notification,
        "queued_channel",
        _FakeQueuedChannel(),
    )

    return notification


def make_graph():
    persistence = build_persistence_foundation(
        config=DatabaseConfig.sqlite_memory()
    )

    reporting = build_reporting_foundation(
        persistence=persistence
    )

    orchestrator = TradingRuntimeOrchestrator(
        runtime_id=RuntimeId(
            "M13-COMPOSITION-RUNTIME"
        ),
        trading_date=TRADING_DATE,
        mode=RuntimeMode.DRY_RUN,
        event_bus=RuntimeEventBus(),
        created_at=CREATED_AT,
    )

    registry = PositionRegistry()

    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    runtime_startup = object.__new__(
        PhoenixRuntimeStartupContainer
    )

    object.__setattr__(
        runtime_startup,
        "persistence",
        persistence,
    )

    object.__setattr__(
        runtime_startup,
        "scheduler",
        scheduler,
    )

    object.__setattr__(
        runtime_startup,
        "orchestrator",
        orchestrator,
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
        "runtime_startup",
        runtime_startup,
    )

    object.__setattr__(
        trading_runtime,
        "position_registry",
        registry,
    )

    dhan = SimpleNamespace(
        account_id=SimpleNamespace(
            value="DHAN-001",
        ),
        account_adapter=SimpleNamespace(
            broker=SimpleNamespace(
                value="DHAN",
            ),
        ),
    )

    object.__setattr__(
        trading_runtime,
        "dhan",
        dhan,
    )

    # Passive M10 control owner required by the M13
    # composition/status graph. No persistence, broker,
    # risk, or command operation is performed by this fixture.
    trading_control = SimpleNamespace(
        snapshot=None,
    )

    object.__setattr__(
        trading_runtime,
        "trading_control",
        trading_control,
    )


    object.__setattr__(
        trading_runtime,
        "signal_runtime",
        object(),
    )

    object.__setattr__(
        trading_runtime,
        "entry_runtime",
        object(),
    )

    return (
        persistence,
        reporting,
        runtime_startup,
        trading_runtime,
        orchestrator,
        registry,
    )


def test_operator_api_reuses_exact_m07_m08_m12_owners():
    (
        persistence,
        reporting,
        runtime_startup,
        trading_runtime,
        orchestrator,
        registry,
    ) = make_graph()

    try:
        api = build_operator_api_foundation(
            runtime_startup=runtime_startup,
            trading_runtime=trading_runtime,
            reporting=reporting,
                    exit_runtime=_operator_exit_runtime(trading_runtime),
            notification=_operator_notification_container(runtime_startup),
        )

        assert isinstance(
            api,
            PhoenixOperatorApiContainer,
        )

        assert (
            api.notification.runtime_startup
            is runtime_startup
        )

        assert (
            api.operator_notifications
            .summary_collector
            is api.notification.summary_collector
        )

        assert (
            api.operator_notifications
            .queued_channel
            is api.notification.queued_channel
        )

        assert (
            api.operator_transport.notifications
            is api.operator_notifications
        )

        assert (
            api.operator_scheduler.scheduler
            is runtime_startup.scheduler
        )

        assert (
            api.operator_transport.scheduler
            is api.operator_scheduler
        )

        assert api.runtime_startup is runtime_startup
        assert api.trading_runtime is trading_runtime
        assert api.reporting is reporting

        assert (
            api.operator_snapshot.runtime
            is orchestrator
        )

        assert (
            api.operator_snapshot.positions
            is registry
        )

        assert (
            api.operator_reporting.runtime
            is orchestrator
        )

        assert (
            api.operator_reporting.runtime_report
            is reporting.runtime_report
        )

        assert (
            api.operator_reporting.daily_report
            is reporting.daily_report
        )

        assert (
            api.operator_reporting.serializer
            is reporting.report_serializer
        )

        assert (
            api.operator_account.account_repository
            is persistence.broker_account_repository
        )

        assert (
            api.operator_account.session_repository
            is persistence.broker_session_repository
        )

        assert (
            api.operator_account.fund_repository
            is persistence.account_fund_repository
        )

        assert (
            api.operator_account.connectivity_repository
            is persistence.broker_connectivity_repository
        )

        assert (
            api.operator_account.health_repository
            is persistence.account_health_repository
        )

        assert (
            api.operator_account.eligibility_repository
            is persistence.account_eligibility_repository
        )

        assert (
            api.operator_account.account_id
            == trading_runtime.dhan.account_id.value
        )

        assert (
            api.operator_account.broker
            == trading_runtime.dhan.account_adapter.broker.value
        )

        assert (
            api.operator_strategy.signal_runtime
            is trading_runtime.signal_runtime
        )

        assert (
            api.operator_strategy.entry_runtime
            is trading_runtime.entry_runtime
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_bootstrap_preserves_exact_reporting_graph():
    (
        persistence,
        reporting,
        runtime_startup,
        trading_runtime,
        _,
        _,
    ) = make_graph()

    try:
        api = compose_operator_api_foundation(
            runtime_startup=runtime_startup,
            trading_runtime=trading_runtime,
            reporting=reporting,
                    exit_runtime=_operator_exit_runtime(trading_runtime),
            notification=_operator_notification_container(runtime_startup),
        )

        assert api.reporting is reporting

        assert (
            api.operator_reporting.runtime_report
            is reporting.runtime_report
        )

        assert (
            api.operator_reporting.daily_report
            is reporting.daily_report
        )

        assert (
            api.operator_reporting.serializer
            is reporting.report_serializer
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_mismatched_runtime_graph_fails_closed():
    (
        persistence,
        reporting,
        runtime_startup,
        trading_runtime,
        _,
        _,
    ) = make_graph()

    try:
        other_runtime_startup = object.__new__(
            PhoenixRuntimeStartupContainer
        )

        object.__setattr__(
            other_runtime_startup,
            "persistence",
            persistence,
        )

        object.__setattr__(
            other_runtime_startup,
            "orchestrator",
            runtime_startup.orchestrator,
        )

        with pytest.raises(
            ValueError,
            match="exact runtime_startup",
        ):
            build_operator_api_foundation(
                runtime_startup=other_runtime_startup,
                trading_runtime=trading_runtime,
                reporting=reporting,
                            exit_runtime=_operator_exit_runtime(trading_runtime),
                notification=_operator_notification_container(other_runtime_startup),
            )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_mismatched_reporting_persistence_fails_closed():
    (
        persistence,
        _,
        runtime_startup,
        trading_runtime,
        _,
        _,
    ) = make_graph()

    other_persistence = build_persistence_foundation(
        config=DatabaseConfig.sqlite_memory()
    )

    other_reporting = build_reporting_foundation(
        persistence=other_persistence
    )

    try:
        with pytest.raises(
            ValueError,
            match="exact trading runtime persistence",
        ):
            build_operator_api_foundation(
                runtime_startup=runtime_startup,
                trading_runtime=trading_runtime,
                reporting=other_reporting,
                            exit_runtime=_operator_exit_runtime(trading_runtime),
                notification=_operator_notification_container(runtime_startup),
            )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()

        other_persistence.sessions.stop()
        other_persistence.database.dispose()
