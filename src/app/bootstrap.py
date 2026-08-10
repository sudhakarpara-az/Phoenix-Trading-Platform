"""
Phoenix Trading Platform.

Application bootstrap composition boundary.

Importing this module must not:
    - connect to Dhan,
    - start the database,
    - start the trading runtime,
    - transition the trading-day scheduler,
    - submit or reconcile orders.
"""

from __future__ import annotations

from datetime import datetime
from typing import (
    Any,
    Callable,
)

from src.account.dhan_account_adapter import (
    DhanAccountAdapter,
)
from src.app.container import (
    PhoenixDhanContainer,
    PhoenixExitRuntimeContainer,
    PhoenixPersistenceContainer,
    PhoenixRuntimeStartupContainer,
    PhoenixTradingRuntimeContainer,
    build_dhan_foundation,
    build_exit_runtime_foundation,
    build_persistence_foundation,
    build_runtime_startup_foundation,
    build_trading_day_end_of_day,
    build_trading_runtime_foundation,
)
from src.app.trading_day_runtime import (
    TradingDayCloseReadinessProvider,
    TradingDayEntryRuntimeCoordinator,
)
from src.account.account_runtime_service import (
    AccountRuntimeService,
)
from src.broker.dhan_broker import (
    DhanBroker,
)
from src.database.engine import (
    DatabaseConfig,
)
from src.execution.order_pricing_policy import (
    OrderPricingPolicy,
)
from src.execution.quantity_policy import (
    QuantityPolicy,
)
from src.market.tick_processor import (
    TickProcessor,
)
from src.risk.stop_loss_policy import (
    StopLossPolicy,
)
from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.recovery_types import (
    BrokerRecoveryProvider,
    RecoveryStateRestorer,
)
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeMode,
)
from src.services.scheduler import (
    TradingDayEndOfDayCoordinator,
    TradingDayScheduler,
    TradingDayTickMonitoringCoordinator,
)
from src.signals.signal_engine import (
    SignalEngine,
)


def compose_persistence_foundation(
    *,
    config: DatabaseConfig | None = None,
) -> PhoenixPersistenceContainer:
    """
    Start and return the shared Phoenix persistence graph.
    """

    return build_persistence_foundation(
        config=config
    )




def compose_dhan_foundation(
    *,
    profile_fetcher: Callable[[], Any],
    broker: DhanBroker | None = None,
) -> PhoenixDhanContainer:
    """
    Compose the shared Dhan execution/account graph.

    This wrapper deliberately delegates object ownership to the
    application container and does not duplicate broker clients.
    """

    return build_dhan_foundation(
        profile_fetcher=profile_fetcher,
        broker=broker,
    )


def compose_runtime_startup_foundation(
    *,
    persistence: PhoenixPersistenceContainer,
    scheduler: TradingDayScheduler,
    broker_provider: BrokerRecoveryProvider,
    state_restorer: RecoveryStateRestorer,
    runtime_id: RuntimeId,
    mode: RuntimeMode,
    created_at: datetime,
    event_bus: RuntimeEventBus | None = None,
) -> PhoenixRuntimeStartupContainer:
    """
    Compose recovery discovery and the M08 runtime object graph.

    The runtime remains CREATED. Lifecycle start is deliberately
    owned by TradingDayStartupCoordinator.
    """

    return build_runtime_startup_foundation(
        persistence=persistence,
        scheduler=scheduler,
        broker_provider=broker_provider,
        state_restorer=state_restorer,
        runtime_id=runtime_id,
        mode=mode,
        created_at=created_at,
        event_bus=event_bus,
    )



def compose_trading_runtime_foundation(
    *,
    persistence: PhoenixPersistenceContainer,
    dhan: PhoenixDhanContainer,
    runtime_startup: PhoenixRuntimeStartupContainer,
    account_runtime: AccountRuntimeService,
    tick_monitor: TradingDayTickMonitoringCoordinator,
    tick_processor: TickProcessor,
    signal_engine: SignalEngine,
    dry_run: bool,
    preferred_lots: int = 1,
    allow_live_orders: bool = False,
    pricing_policy: OrderPricingPolicy | None = None,
    quantity_policy: QuantityPolicy | None = None,
    stop_loss_policy: StopLossPolicy | None = None,
) -> PhoenixTradingRuntimeContainer:
    """
    Compose the full M10 market-to-durable-entry graph.
    """

    return build_trading_runtime_foundation(
        persistence=persistence,
        dhan=dhan,
        runtime_startup=runtime_startup,
        account_runtime=account_runtime,
        tick_monitor=tick_monitor,
        tick_processor=tick_processor,
        signal_engine=signal_engine,
        dry_run=dry_run,
        preferred_lots=preferred_lots,
        allow_live_orders=allow_live_orders,
        pricing_policy=pricing_policy,
        quantity_policy=quantity_policy,
        stop_loss_policy=stop_loss_policy,
    )



def compose_exit_runtime_foundation(
    *,
    persistence: PhoenixPersistenceContainer,
    dhan: PhoenixDhanContainer,
    trading_runtime:
        PhoenixTradingRuntimeContainer,
    allow_live_exit_orders: bool = False,
) -> PhoenixExitRuntimeContainer:
    """
    Compose shared durable SELL / force-exit / EOD graph.
    """

    return build_exit_runtime_foundation(
        persistence=persistence,
        dhan=dhan,
        trading_runtime=trading_runtime,
        allow_live_exit_orders=(
            allow_live_exit_orders
        ),
    )


def compose_trading_day_end_of_day(
    *,
    scheduler: TradingDayScheduler,
    entry_runtime:
        TradingDayEntryRuntimeCoordinator,
    account_adapter: DhanAccountAdapter,
    durable_order_repository=None,
    runtime_id: str | None = None,
) -> tuple[
    TradingDayCloseReadinessProvider,
    TradingDayEndOfDayCoordinator,
]:
    """
    Prepare the existing M10 end-of-day application graph.
    """

    return build_trading_day_end_of_day(
        scheduler=scheduler,
        entry_runtime=entry_runtime,
        account_adapter=account_adapter,
        durable_order_repository=(
            durable_order_repository
        ),
        runtime_id=runtime_id,
    )



# ============================================================
# Production restart-recovery bootstrap helpers
# ============================================================

from src.app.container import (
    build_dhan_recovery_provider,
    build_recovery_foundation,
    build_recovery_state_restorer_binding,
)
from src.app.recovery import (
    PhoenixDhanRecoveryProvider,
    PhoenixRecoveryStateRestorer,
    RecoveryStateRestorerBinding,
)


def compose_dhan_recovery_provider(
    *,
    dhan: PhoenixDhanContainer,
) -> PhoenixDhanRecoveryProvider:
    """
    Prepare exact Dhan broker truth for startup recovery.
    """

    return build_dhan_recovery_provider(
        dhan=dhan
    )


def compose_recovery_state_restorer_binding(
) -> RecoveryStateRestorerBinding:
    """
    Prepare the deferred state-restorer boundary needed before
    the complete M06/M07 runtime graph exists.
    """

    return (
        build_recovery_state_restorer_binding()
    )


def compose_recovery_foundation(
    *,
    persistence: PhoenixPersistenceContainer,
    dhan: PhoenixDhanContainer,
    runtime_startup:
        PhoenixRuntimeStartupContainer,
    trading_runtime:
        PhoenixTradingRuntimeContainer,
    exit_runtime:
        PhoenixExitRuntimeContainer,
    broker_provider:
        PhoenixDhanRecoveryProvider,
    state_restorer_binding:
        RecoveryStateRestorerBinding,
) -> PhoenixRecoveryStateRestorer:
    """
    Bind the concrete restart state restorer after the exact
    trading and exit runtime owners have been composed.
    """

    return build_recovery_foundation(
        persistence=persistence,
        dhan=dhan,
        runtime_startup=runtime_startup,
        trading_runtime=trading_runtime,
        exit_runtime=exit_runtime,
        broker_provider=broker_provider,
        state_restorer_binding=(
            state_restorer_binding
        ),
    )



__all__ = [
    "compose_dhan_foundation",
    "compose_exit_runtime_foundation",
    "compose_persistence_foundation",
    "compose_runtime_startup_foundation",
    "compose_trading_day_end_of_day",
    "compose_trading_runtime_foundation",
    "compose_dhan_recovery_provider",
    "compose_recovery_state_restorer_binding",
    "compose_recovery_foundation",
]
