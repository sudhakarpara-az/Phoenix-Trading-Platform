"""
M10 production composition tests for the complete
market -> signal -> durable entry runtime spine.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from typing import (
    Any,
    cast,
)

import pytest

import src.app.container as container_module

from src.account.account_runtime_service import (
    AccountRuntimeService,
)
from src.account.account_types import (
    BrokerType,
)
from src.app.container import (
    PhoenixTradingRuntimeContainer,
    build_dhan_foundation,
    build_persistence_foundation,
    build_runtime_startup_foundation,
    build_trading_runtime_foundation,
)
from src.broker.dhan_broker import (
    DhanBroker,
)
from src.database.engine import (
    DatabaseConfig,
)
from src.database.entry_durability import (
    DurableEntryBrokerExecutionProvider,
)
from src.market.tick_processor import (
    TickProcessor,
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
    TradingDayTickMonitoringCoordinator,
)
from src.signals.signal_engine import (
    SignalEngine,
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
            "clean composition must not query broker"
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
            "clean composition must not query broker"
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
            "clean composition must not restore order"
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
            "clean composition must not restore position"
        )


class _CaptureFactory:
    def __init__(self) -> None:
        self.calls: list[
            dict[str, Any]
        ] = []

    def __call__(
        self,
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            kwargs
        )

        return SimpleNamespace(
            **kwargs
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
        "DHAN-RUNTIME-COMPOSITION"
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
                    "DHAN-RUNTIME-COMPOSITION"
            }
        ),
    )


def _make_account_runtime(
    account_id,
) -> AccountRuntimeService:
    runtime = object.__new__(
        AccountRuntimeService
    )

    test_runtime = cast(
        Any,
        runtime,
    )

    test_runtime._broker = (
        BrokerType.DHAN
    )

    test_runtime._account_id = (
        account_id
    )

    return runtime


def _make_tick_monitor(
    *,
    scheduler: TradingDayScheduler,
) -> TradingDayTickMonitoringCoordinator:
    monitor = object.__new__(
        TradingDayTickMonitoringCoordinator
    )

    preparation = SimpleNamespace(
        selected_call=object(),
        selected_put=object(),
    )

    test_monitor = cast(
        Any,
        monitor,
    )

    test_monitor._scheduler = (
        scheduler
    )

    test_monitor._preparation = (
        preparation
    )

    return monitor


def test_full_entry_composition_activates_t14_durability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

        runtime_startup = (
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
                    "PHOENIX-COMPOSED-RUNTIME"
                ),
                mode=RuntimeMode.DRY_RUN,
                created_at=CREATED_AT,
            )
        )

        account_runtime = (
            _make_account_runtime(
                dhan.account_id
            )
        )

        tick_monitor = (
            _make_tick_monitor(
                scheduler=scheduler
            )
        )

        tick_processor = (
            object.__new__(
                TickProcessor
            )
        )

        signal_engine = (
            object.__new__(
                SignalEngine
            )
        )

        signal_factory = (
            _CaptureFactory()
        )
        entry_factory = (
            _CaptureFactory()
        )
        tick_factory = (
            _CaptureFactory()
        )
        ingress_factory = (
            _CaptureFactory()
        )

        monkeypatch.setattr(
            container_module,
            "TradingDaySignalRuntimeCoordinator",
            signal_factory,
        )

        monkeypatch.setattr(
            container_module,
            "TradingDayEntryRuntimeCoordinator",
            entry_factory,
        )

        monkeypatch.setattr(
            container_module,
            "TradingDayTickRuntimeCoordinator",
            tick_factory,
        )

        monkeypatch.setattr(
            container_module,
            "TradingDayMarketIngressHandler",
            ingress_factory,
        )

        runtime = (
            build_trading_runtime_foundation(
                persistence=persistence,
                dhan=dhan,
                runtime_startup=(
                    runtime_startup
                ),
                account_runtime=(
                    account_runtime
                ),
                tick_monitor=tick_monitor,
                tick_processor=(
                    tick_processor
                ),
                signal_engine=signal_engine,
                dry_run=True,
                preferred_lots=1,
                allow_live_orders=False,
            )
        )

        assert isinstance(
            runtime,
            PhoenixTradingRuntimeContainer,
        )

        # --------------------------------------------
        # Foundation ownership
        # --------------------------------------------

        assert (
            runtime.persistence
            is persistence
        )

        assert runtime.dhan is dhan

        assert (
            runtime.runtime_startup
            is runtime_startup
        )

        assert (
            runtime.entry_gate.scheduler
            is scheduler
        )

        # --------------------------------------------
        # T14 durability is actually in the M06 path.
        # --------------------------------------------

        assert isinstance(
            runtime.durable_entry_provider,
            DurableEntryBrokerExecutionProvider,
        )

        assert (
            runtime
            .durable_entry_provider
            .delegate
            is dhan.order_adapter
        )

        assert (
            runtime
            .durable_entry_provider
            .persistence
            is runtime.entry_persistence
        )

        assert (
            runtime
            .execution_service
            .broker_provider
            is runtime.durable_entry_provider
        )

        assert (
            runtime
            .execution_service
            .order_state_machine
            is runtime.order_state_machine
        )

        assert (
            getattr(
                runtime.entry_persistence,
                "_position_repository",
            )
            is persistence.position_repository
        )

        # --------------------------------------------
        # Exact M06 sizing-policy ownership.
        # --------------------------------------------

        assert (
            runtime
            .entry_adapter
            .execution_service
            is runtime.execution_service
        )

        # --------------------------------------------
        # Exact M09 account identity.
        # --------------------------------------------

        assert (
            runtime.account_gate.broker
            is BrokerType.DHAN
        )

        assert (
            runtime.account_gate.account_id
            == dhan.account_id
        )

        assert (
            runtime.account_gate
            .entry_execution
            is runtime.entry_adapter
        )

        # --------------------------------------------
        # Exact shared M07 PositionRegistry.
        # --------------------------------------------

        assert (
            runtime
            .position_initializer
            .registry
            is runtime.position_registry
        )

        assert (
            runtime
            .exposure_policy
            .registry
            is runtime.position_registry
        )

        assert (
            runtime
            .daily_risk_manager
            .registry
            is runtime.position_registry
        )

        # --------------------------------------------
        # Downstream composition receives exact owners.
        # Existing component suites validate their internal
        # constructor contracts separately.
        # --------------------------------------------

        assert len(
            signal_factory.calls
        ) == 1

        signal_kwargs = (
            signal_factory.calls[0]
        )

        assert (
            signal_kwargs["entry_gate"]
            is runtime.entry_gate
        )

        assert (
            signal_kwargs["signal_engine"]
            is signal_engine
        )

        assert len(
            entry_factory.calls
        ) == 1

        entry_kwargs = (
            entry_factory.calls[0]
        )

        assert (
            entry_kwargs["entry_adapter"]
            is runtime.entry_adapter
        )

        assert (
            entry_kwargs["account_gate"]
            is runtime.account_gate
        )

        assert (
            entry_kwargs["exposure_policy"]
            is runtime.exposure_policy
        )

        assert (
            entry_kwargs["daily_risk_manager"]
            is runtime.daily_risk_manager
        )

        assert (
            entry_kwargs["position_initializer"]
            is runtime.position_initializer
        )

        assert (
            entry_kwargs["level_preparation"]
            is tick_monitor.preparation
        )

        assert len(
            tick_factory.calls
        ) == 1

        assert (
            tick_factory.calls[0]
            ["tick_monitor"]
            is tick_monitor
        )

        assert len(
            ingress_factory.calls
        ) == 1

        assert (
            ingress_factory.calls[0]
            ["tick_processor"]
            is tick_processor
        )

        assert (
            ingress_factory.calls[0]
            ["dry_run"]
            is True
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_entry_composition_rejects_account_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch

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

        scheduler = TradingDayScheduler(
            trading_date=TRADING_DATE,
            created_at=CREATED_AT,
        )

        runtime_startup = (
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
                    "IDENTITY-MISMATCH"
                ),
                mode=RuntimeMode.DRY_RUN,
                created_at=CREATED_AT,
            )
        )

        account_runtime = (
            _make_account_runtime(
                dhan.account_id
            )
        )

        cast(
            Any,
            account_runtime,
        )._account_id = (
            dhan.account_id.__class__(
                "DIFFERENT-DHAN-ACCOUNT"
            )
        )

        with pytest.raises(
            ValueError,
            match=(
                "account_runtime account_id "
                "must match"
            ),
        ):
            build_trading_runtime_foundation(
                persistence=persistence,
                dhan=dhan,
                runtime_startup=runtime_startup,
                account_runtime=account_runtime,
                tick_monitor=(
                    _make_tick_monitor(
                        scheduler=scheduler
                    )
                ),
                tick_processor=(
                    object.__new__(
                        TickProcessor
                    )
                ),
                signal_engine=(
                    object.__new__(
                        SignalEngine
                    )
                ),
                dry_run=True,
            )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()
