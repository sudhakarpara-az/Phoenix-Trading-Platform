"""
Phoenix Trading Platform.

Application composition boundaries.

This module owns construction relationships between already
implemented Phoenix components. It does not own domain logic,
broker logic, scheduler policy, or trading decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import (
    Any,
    Callable,
)

from src.account.account_execution_gate import (
    AccountExecutionSafetyGate,
)
from src.account.account_runtime_service import (
    AccountRuntimeService,
)
from src.account.account_types import (
    BrokerAccountId,
    BrokerType,
)
from src.account.dhan_account_adapter import (
    DhanAccountAdapter,
)
from src.broker.dhan_broker import (
    DhanBroker,
)
from src.app.trading_day_runtime import (
    TradingDayCloseReadinessProvider,
    TradingDayForceExitRuntimeCoordinator,
    TradingDayEntryRuntimeCoordinator,
    TradingDayMarketIngressHandler,
    TradingDaySignalRuntimeCoordinator,
    TradingDayTickRuntimeCoordinator,
)
from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.database.entry_durability import (
    DurableEntryBrokerExecutionProvider,
    SQLAlchemyEntryPersistenceService,
)
from src.database.exit_durability import (
    DurableExitExecutionProvider,
    SQLAlchemyExitPersistenceService,
)
from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyAccountEligibilitySnapshotRepository,
    SQLAlchemyAccountFundSnapshotRepository,
    SQLAlchemyAccountHealthSnapshotRepository,
    SQLAlchemyAuditEventRepository,
    SQLAlchemyBrokerAccountRepository,
    SQLAlchemyBrokerConnectivitySnapshotRepository,
    SQLAlchemyBrokerSessionRepository,
    SQLAlchemyOptionSelectionRepository,
    SQLAlchemyOrderFillRepository,
    SQLAlchemyOrderRepository,
    SQLAlchemyPositionRepository,
    SQLAlchemyRuntimeSessionRepository,
    SQLAlchemySignalRepository,
)
from src.database.schema import (
    create_schema,
)
from src.database.session import (
    DatabaseSessionManager,
)
from src.execution.dhan_exit_order_adapter import (
    DhanExitOrderAdapter,
)
from src.execution.dhan_order_adapter import (
    DhanOrderAdapter,
)
from src.execution.execution_service import (
    ExecutionService,
)
from src.execution.execution_types import ExecutionMode
from src.execution.exit_execution_service import (
    ExitExecutionService,
)
from src.execution.exit_plan_builder import (
    ExitPlanBuilder,
)
from src.execution.exit_reconciliation_service import (
    ExitReconciliationService,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
)
from src.execution.filled_position_builder import (
    FilledPositionBuilder,
)
from src.execution.m06_entry_runtime_adapter import (
    M06EntryRuntimeAdapter,
)
from src.execution.order_eligibility_validator import (
    OrderEligibilityValidator,
)
from src.execution.order_pricing_policy import (
    OrderPricingPolicy,
)
from src.execution.order_state_machine import (
    OrderStateMachine,
)
from src.execution.quantity_policy import (
    QuantityPolicy,
)
from src.execution.target_booking_policy import (
    TargetBookingPolicy,
)
from src.market.tick_processor import (
    TickProcessor,
)
from src.risk.daily_risk_manager import (
    DailyRiskManager,
)
from src.risk.exposure_risk_policy import (
    ExposureRiskPolicy,
)
from src.risk.filled_position_risk_initializer import (
    FilledPositionRiskInitializer,
)
from src.risk.option_target_mapper import (
    OptionTargetMapper,
)
from src.risk.force_exit_coordinator import (
    ForceExitCoordinator,
)
from src.risk.m06_exit_integration_service import (
    M07ToM06ExitIntegrationService,
)
from src.risk.position_lifecycle_manager import (
    PositionLifecycleManager,
)
from src.risk.position_pnl_tracker import (
    PositionPnLTracker,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.stop_loss_policy import (
    StopLossConfig,
    StopLossPolicy,
)
from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.recovery_types import (
    BrokerRecoveryProvider,
    RecoveryStateRestorer,
    StartupRecoveryPlan,
)
from src.runtime.runtime_orchestrator import (
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeMode,
)
from src.runtime.startup_recovery_service import (
    StartupRecoveryService,
)
from src.services.scheduler import (
    TradingDayEndOfDayCoordinator,
    TradingDayEntryGateCoordinator,
    TradingDayForceExitCoordinator,
    TradingDayScheduler,
    TradingDayStartupCoordinator,
    TradingDayTickMonitoringCoordinator,
)
from src.signals.signal_engine import (
    SignalEngine,
)


@dataclass(
    frozen=True,
    slots=True,
)
class PhoenixPersistenceContainer:
    """
    Shared Phoenix persistence object graph.

    Every repository uses the exact same
    DatabaseSessionManager and DatabaseEngine.
    """

    database: DatabaseEngine
    sessions: DatabaseSessionManager

    runtime_repository: SQLAlchemyRuntimeSessionRepository
    signal_repository: SQLAlchemySignalRepository
    option_selection_repository: SQLAlchemyOptionSelectionRepository
    order_repository: SQLAlchemyOrderRepository
    order_fill_repository: SQLAlchemyOrderFillRepository
    position_repository: SQLAlchemyPositionRepository
    audit_repository: SQLAlchemyAuditEventRepository

    broker_account_repository: SQLAlchemyBrokerAccountRepository
    broker_session_repository: SQLAlchemyBrokerSessionRepository
    account_fund_repository: SQLAlchemyAccountFundSnapshotRepository
    broker_connectivity_repository: SQLAlchemyBrokerConnectivitySnapshotRepository
    account_health_repository: SQLAlchemyAccountHealthSnapshotRepository
    account_eligibility_repository: SQLAlchemyAccountEligibilitySnapshotRepository


def build_persistence_foundation(
    *,
    config: DatabaseConfig | None = None,
) -> PhoenixPersistenceContainer:
    """
    Build and start the shared Phoenix persistence foundation.

    Required lifecycle:

        DatabaseEngine
            ->
        create_schema()
            ->
        DatabaseSessionManager
            ->
        all SQLAlchemy repositories

    Construction is fail-safe. If any later persistence
    construction step fails, already-started resources are
    released before the exception propagates.
    """

    database = DatabaseEngine(
        config=config
    )

    sessions: (
        DatabaseSessionManager | None
    ) = None

    try:
        engine = database.start()

        create_schema(
            engine
        )

        session_manager = (
            DatabaseSessionManager(
                database_engine=database
            )
        )

        sessions = session_manager

        session_manager.start()

        return PhoenixPersistenceContainer(
            database=database,
            sessions=session_manager,

            runtime_repository=(
                SQLAlchemyRuntimeSessionRepository(
                    sessions=session_manager
                )
            ),
            signal_repository=(
                SQLAlchemySignalRepository(
                    sessions=session_manager
                )
            ),
            option_selection_repository=(
                SQLAlchemyOptionSelectionRepository(
                    sessions=session_manager
                )
            ),
            order_repository=(
                SQLAlchemyOrderRepository(
                    sessions=session_manager
                )
            ),
            order_fill_repository=(
                SQLAlchemyOrderFillRepository(
                    sessions=session_manager
                )
            ),
            position_repository=(
                SQLAlchemyPositionRepository(
                    sessions=session_manager
                )
            ),
            audit_repository=(
                SQLAlchemyAuditEventRepository(
                    sessions=session_manager
                )
            ),

            broker_account_repository=(
                SQLAlchemyBrokerAccountRepository(
                    sessions=session_manager
                )
            ),
            broker_session_repository=(
                SQLAlchemyBrokerSessionRepository(
                    sessions=session_manager
                )
            ),
            account_fund_repository=(
                SQLAlchemyAccountFundSnapshotRepository(
                    sessions=session_manager
                )
            ),
            broker_connectivity_repository=(
                SQLAlchemyBrokerConnectivitySnapshotRepository(
                    sessions=session_manager
                )
            ),
            account_health_repository=(
                SQLAlchemyAccountHealthSnapshotRepository(
                    sessions=session_manager
                )
            ),
            account_eligibility_repository=(
                SQLAlchemyAccountEligibilitySnapshotRepository(
                    sessions=session_manager
                )
            ),
        )

    except Exception:

        if sessions is not None:
            sessions.stop()

        database.dispose()

        raise




@dataclass(
    frozen=True,
    slots=True,
)
class PhoenixDhanContainer:
    """
    Shared Dhan broker object graph.

    Exactly one authenticated Dhan SDK client is shared by:
        - entry execution,
        - exit execution,
        - account/profile/funds/connectivity,
        - broker-wide EOD truth.

    Construction performs no broker API request beyond whatever
    DhanBroker itself requires to establish its SDK client.
    """

    broker: DhanBroker
    client: Any
    account_id: BrokerAccountId
    order_adapter: DhanOrderAdapter
    exit_order_adapter: DhanExitOrderAdapter
    account_adapter: DhanAccountAdapter


def build_dhan_foundation(
    *,
    profile_fetcher: Callable[[], Any],
    broker: DhanBroker | None = None,
) -> PhoenixDhanContainer:
    """
    Build the shared Dhan execution/account composition graph.

    Production may omit ``broker`` so this boundary constructs
    the existing DhanBroker.

    Tests and controlled integrations may inject an existing
    DhanBroker instance.

    No second Dhan SDK client is created. Every downstream
    adapter receives broker.get_client().
    """

    if not callable(
        profile_fetcher
    ):
        raise TypeError(
            "profile_fetcher must be callable"
        )

    resolved_broker = (
        broker
        if broker is not None
        else DhanBroker()
    )

    if not isinstance(
        resolved_broker,
        DhanBroker,
    ):
        raise TypeError(
            "broker must be DhanBroker"
        )

    client = (
        resolved_broker.get_client()
    )

    if client is None:
        raise RuntimeError(
            "DhanBroker returned no authenticated client"
        )

    account_id = BrokerAccountId(
        resolved_broker.client_id
    )

    order_adapter = DhanOrderAdapter(
        client
    )

    exit_order_adapter = (
        DhanExitOrderAdapter(
            client
        )
    )

    account_adapter = (
        DhanAccountAdapter(
            dhan_client=client,
            profile_fetcher=profile_fetcher,
            account_id=account_id,
        )
    )

    return PhoenixDhanContainer(
        broker=resolved_broker,
        client=client,
        account_id=account_id,
        order_adapter=order_adapter,
        exit_order_adapter=(
            exit_order_adapter
        ),
        account_adapter=account_adapter,
    )



@dataclass(
    frozen=True,
    slots=True,
)
class PhoenixTradingRuntimeContainer:
    """
    Active Phoenix market -> signal -> durable BUY runtime graph.

    Ownership invariants:

        one M10 TradingDayScheduler
        one M08 TradingRuntimeOrchestrator
        one M06 OrderStateMachine
        one T14 durable broker provider
        one M07 PositionRegistry
        one M09 AccountExecutionSafetyGate

    The same objects are reused throughout the entry path.
    """

    persistence: PhoenixPersistenceContainer
    dhan: PhoenixDhanContainer
    runtime_startup: PhoenixRuntimeStartupContainer

    entry_gate: TradingDayEntryGateCoordinator

    order_state_machine: OrderStateMachine
    entry_persistence: SQLAlchemyEntryPersistenceService
    durable_entry_provider: DurableEntryBrokerExecutionProvider

    execution_service: ExecutionService
    entry_adapter: M06EntryRuntimeAdapter
    account_gate: AccountExecutionSafetyGate

    position_registry: PositionRegistry
    stop_loss_policy: StopLossPolicy
    position_initializer: FilledPositionRiskInitializer
    exposure_policy: ExposureRiskPolicy
    daily_risk_manager: DailyRiskManager
    pnl_tracker: PositionPnLTracker

    filled_position_builder: FilledPositionBuilder

    target_mapper: OptionTargetMapper

    signal_runtime: TradingDaySignalRuntimeCoordinator

    entry_runtime: TradingDayEntryRuntimeCoordinator

    tick_runtime: TradingDayTickRuntimeCoordinator

    market_ingress: TradingDayMarketIngressHandler


def build_trading_runtime_foundation(
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
    Compose the complete active Phoenix BUY-entry spine.

    Important:

        DhanOrderAdapter
            ->
        DurableEntryBrokerExecutionProvider
            ->
        ExecutionService
            ->
        M06EntryRuntimeAdapter
            ->
        AccountExecutionSafetyGate
            ->
        TradingDayEntryRuntimeCoordinator

    This activates T14 persistence at the actual broker boundary.

    Construction itself performs no BUY and processes no tick.
    """

    # --------------------------------------------------------
    # Identity / safety validation
    # --------------------------------------------------------

    if (
        runtime_startup.persistence
        is not persistence
    ):
        raise ValueError(
            "runtime_startup must own the exact "
            "persistence container"
        )

    if (
        tick_monitor.scheduler
        is not runtime_startup.scheduler
    ):
        raise ValueError(
            "tick monitor must share the exact "
            "TradingDayScheduler"
        )

    if (
        account_runtime.broker
        is not BrokerType.DHAN
    ):
        raise ValueError(
            "account_runtime broker must be DHAN"
        )

    if (
        account_runtime.account_id
        != dhan.account_id
    ):
        raise ValueError(
            "account_runtime account_id must match "
            "the Dhan composition account"
        )

    if type(dry_run) is not bool:
        raise TypeError(
            "dry_run must be bool"
        )

    if type(allow_live_orders) is not bool:
        raise TypeError(
            "allow_live_orders must be bool"
        )

    if (
        isinstance(preferred_lots, bool)
        or not isinstance(
            preferred_lots,
            int,
        )
    ):
        raise TypeError(
            "preferred_lots must be an integer"
        )

    if preferred_lots <= 0:
        raise ValueError(
            "preferred_lots must be greater than zero"
        )

    # --------------------------------------------------------
    # M10 + M08 global entry gate
    # --------------------------------------------------------

    entry_gate = (
        TradingDayEntryGateCoordinator(
            scheduler=(
                runtime_startup.scheduler
            ),
            runtime_gate=(
                runtime_startup.orchestrator
            ),
        )
    )

    # --------------------------------------------------------
    # M04 fixed-contract signal runtime
    #
    # Never re-select options here.
    # T09/T07 preparation remains authoritative.
    # --------------------------------------------------------

    preparation = (
        tick_monitor.preparation
    )

    signal_runtime = (
        TradingDaySignalRuntimeCoordinator(
            entry_gate=entry_gate,
            signal_engine=signal_engine,
            selected_call=(
                preparation.selected_call
            ),
            selected_put=(
                preparation.selected_put
            ),
        )
    )

    # --------------------------------------------------------
    # M07 exact shared PositionRegistry
    # --------------------------------------------------------

    position_registry = (
        PositionRegistry()
    )

    resolved_stop_loss_policy = (
        stop_loss_policy
        if stop_loss_policy is not None
        else StopLossPolicy(
            StopLossConfig(
                risk_points=15.0,
                tick_size=0.05,
            )
        )
    )

    position_initializer = (
        FilledPositionRiskInitializer(
            registry=position_registry,
            stop_loss_policy=(
                resolved_stop_loss_policy
            ),
        )
    )

    exposure_policy = (
        ExposureRiskPolicy(
            registry=position_registry
        )
    )

    daily_risk_manager = (
        DailyRiskManager(
            registry=position_registry
        )
    )

    pnl_tracker = (
        PositionPnLTracker()
    )

    filled_position_builder = (
        FilledPositionBuilder()
    )

    target_mapper = (
        OptionTargetMapper()
    )

    # --------------------------------------------------------
    # M06 + T14 durable broker boundary
    # --------------------------------------------------------

    order_state_machine = (
        OrderStateMachine()
    )

    entry_persistence = (
        SQLAlchemyEntryPersistenceService(
            runtime_id=(
                runtime_startup
                .orchestrator
                .runtime_id
                .value
            ),
            signal_repository=(
                persistence.signal_repository
            ),
            option_selection_repository=(
                persistence
                .option_selection_repository
            ),
            order_repository=(
                persistence.order_repository
            ),
            position_repository=(
                persistence.position_repository
            ),
        )
    )

    durable_entry_provider = (
        DurableEntryBrokerExecutionProvider(
            delegate=dhan.order_adapter,
            persistence=entry_persistence,
            state_machine=(
                order_state_machine
            ),
        )
    )

    resolved_pricing_policy = (
        pricing_policy
        if pricing_policy is not None
        else OrderPricingPolicy()
    )

    resolved_quantity_policy = (
        quantity_policy
        if quantity_policy is not None
        else QuantityPolicy()
    )

    execution_service = (
        ExecutionService(
            pricing_policy=(
                resolved_pricing_policy
            ),
            quantity_policy=(
                resolved_quantity_policy
            ),
            eligibility_validator=(
                OrderEligibilityValidator()
            ),
            state_machine=(
                order_state_machine
            ),
            broker_provider=(
                durable_entry_provider
            ),
            allow_live_orders=(
                allow_live_orders
            ),
        )
    )

    entry_adapter = (
        M06EntryRuntimeAdapter(
            execution_service=(
                execution_service
            ),
            preferred_lots=preferred_lots,
        )
    )

    # --------------------------------------------------------
    # M09 current account safety gate
    # --------------------------------------------------------

    account_gate = (
        AccountExecutionSafetyGate(
            broker=BrokerType.DHAN,
            account_id=dhan.account_id,
            account_runtime=account_runtime,
            entry_execution=entry_adapter,
        )
    )

    # --------------------------------------------------------
    # T14 accepted-signal lifecycle
    # --------------------------------------------------------

    entry_runtime = (
        TradingDayEntryRuntimeCoordinator(
            signal_runtime=signal_runtime,
            entry_adapter=entry_adapter,
            account_gate=account_gate,
            exposure_policy=(
                exposure_policy
            ),
            daily_risk_manager=(
                daily_risk_manager
            ),
            pnl_tracker=pnl_tracker,
            filled_position_builder=(
                filled_position_builder
            ),
            position_initializer=(
                position_initializer
            ),
            target_mapper=target_mapper,
            level_preparation=preparation,
        )
    )

    # --------------------------------------------------------
    # T09 tick -> M04 -> T14 entry path
    # --------------------------------------------------------

    tick_runtime = (
        TradingDayTickRuntimeCoordinator(
            tick_monitor=tick_monitor,
            signal_runtime=signal_runtime,
            entry_runtime=entry_runtime,
        )
    )

    market_ingress = (
        TradingDayMarketIngressHandler(
            tick_processor=tick_processor,
            tick_runtime=tick_runtime,
            dry_run=dry_run,
        )
    )

    return PhoenixTradingRuntimeContainer(
        persistence=persistence,
        dhan=dhan,
        runtime_startup=runtime_startup,
        entry_gate=entry_gate,
        order_state_machine=(
            order_state_machine
        ),
        entry_persistence=(
            entry_persistence
        ),
        durable_entry_provider=(
            durable_entry_provider
        ),
        execution_service=(
            execution_service
        ),
        entry_adapter=entry_adapter,
        account_gate=account_gate,
        position_registry=(
            position_registry
        ),
        stop_loss_policy=(
            resolved_stop_loss_policy
        ),
        position_initializer=(
            position_initializer
        ),
        exposure_policy=(
            exposure_policy
        ),
        daily_risk_manager=(
            daily_risk_manager
        ),
        pnl_tracker=pnl_tracker,
        filled_position_builder=(
            filled_position_builder
        ),
        target_mapper=target_mapper,
        signal_runtime=signal_runtime,
        entry_runtime=entry_runtime,
        tick_runtime=tick_runtime,
        market_ingress=market_ingress,
    )



@dataclass(
    frozen=True,
    slots=True,
)
class PhoenixExitRuntimeContainer:
    """
    Shared M06/M07/M10 exit composition graph.

    This is composition only. Construction does not evaluate the
    15:15 boundary and does not submit/cancel/reconcile a SELL.
    """

    persistence: PhoenixPersistenceContainer
    dhan: PhoenixDhanContainer
    trading_runtime: PhoenixTradingRuntimeContainer

    exit_persistence: SQLAlchemyExitPersistenceService
    durable_exit_provider: DurableExitExecutionProvider

    duplicate_guard: DuplicateOrderGuard
    exit_plan_builder: ExitPlanBuilder
    exit_execution_service: ExitExecutionService

    position_lifecycle_manager: PositionLifecycleManager

    exit_integration: M07ToM06ExitIntegrationService
    exit_reconciliation: ExitReconciliationService

    force_exit_coordinator: ForceExitCoordinator
    trading_day_force_exit: TradingDayForceExitCoordinator

    force_exit_runtime: TradingDayForceExitRuntimeCoordinator

    readiness_provider: TradingDayCloseReadinessProvider
    end_of_day_coordinator: TradingDayEndOfDayCoordinator


def build_exit_runtime_foundation(
    *,
    persistence: PhoenixPersistenceContainer,
    dhan: PhoenixDhanContainer,
    trading_runtime: PhoenixTradingRuntimeContainer,
    allow_live_exit_orders: bool = False,
) -> PhoenixExitRuntimeContainer:
    """
    Compose the complete production SELL / 15:15 dependency graph.

    Identity invariants:

        same PersistenceContainer
        same DhanContainer
        same TradingDayScheduler
        same PositionRegistry
        same DuplicateOrderGuard
        same durable SELL provider
    """

    if (
        trading_runtime.persistence
        is not persistence
    ):
        raise ValueError(
            "trading_runtime must own the exact "
            "persistence container"
        )

    if (
        trading_runtime.dhan
        is not dhan
    ):
        raise ValueError(
            "trading_runtime must own the exact "
            "Dhan container"
        )

    if type(allow_live_exit_orders) is not bool:
        raise TypeError(
            "allow_live_exit_orders must be bool"
        )

    runtime_id = (
        trading_runtime
        .runtime_startup
        .orchestrator
        .runtime_id
        .value
    )

    scheduler = (
        trading_runtime
        .runtime_startup
        .scheduler
    )

    registry = (
        trading_runtime
        .position_registry
    )

    # --------------------------------------------------------
    # Durable SELL boundary
    # --------------------------------------------------------

    exit_persistence = (
        SQLAlchemyExitPersistenceService(
            runtime_id=runtime_id,
            order_repository=(
                persistence.order_repository
            ),
            fill_repository=(
                persistence.order_fill_repository
            ),
            position_repository=(
                persistence.position_repository
            ),
        )
    )

    durable_exit_provider = (
        DurableExitExecutionProvider(
            delegate=(
                dhan.exit_order_adapter
            ),
            persistence=(
                exit_persistence
            ),
        )
    )

    # --------------------------------------------------------
    # One position-level duplicate guard is shared across
    # normal M06 exit execution and force-exit reconciliation.
    # --------------------------------------------------------

    duplicate_guard = (
        DuplicateOrderGuard()
    )

    exit_plan_builder = (
        ExitPlanBuilder(
            TargetBookingPolicy()
        )
    )

    exit_execution_service = (
        ExitExecutionService(
            provider=(
                durable_exit_provider
            ),
            duplicate_guard=(
                duplicate_guard
            ),
            allow_live_exit_orders=(
                allow_live_exit_orders
            ),
        )
    )

    # --------------------------------------------------------
    # Same M07 registry already populated by BUY fills.
    # --------------------------------------------------------

    position_lifecycle_manager = (
        PositionLifecycleManager(
            registry=registry
        )
    )

    exit_integration = (
        M07ToM06ExitIntegrationService(
            registry=registry,
            lifecycle_manager=(
                position_lifecycle_manager
            ),
            exit_plan_builder=(
                exit_plan_builder
            ),
            exit_execution_service=(
                exit_execution_service
            ),
        )
    )

    exit_reconciliation = (
        ExitReconciliationService(
            provider=(
                durable_exit_provider
            ),
            exit_plan_builder=(
                exit_plan_builder
            ),
            duplicate_guard=(
                duplicate_guard
            ),
        )
    )

    # --------------------------------------------------------
    # M07 15:15 evaluation + M10 EXIT_ONLY boundary.
    # --------------------------------------------------------

    force_exit_coordinator = (
        ForceExitCoordinator(
            registry=registry
        )
    )

    trading_day_force_exit = (
        TradingDayForceExitCoordinator(
            scheduler=scheduler,
            force_exit_coordinator=(
                force_exit_coordinator
            ),
        )
    )

    execution_mode = (
        ExecutionMode.LIVE
        if (
            trading_runtime
            .runtime_startup
            .orchestrator
            .mode
            is RuntimeMode.LIVE
        )
        else ExecutionMode.DRY_RUN
    )

    force_exit_runtime = (
        TradingDayForceExitRuntimeCoordinator(
            trading_day_force_exit=(
                trading_day_force_exit
            ),
            exit_integration=(
                exit_integration
            ),
            exit_reconciliation=(
                exit_reconciliation
            ),
            exit_persistence=(
                exit_persistence
            ),
            durable_exit_provider=(
                durable_exit_provider
            ),
            position_lifecycle_manager=(
                position_lifecycle_manager
            ),
            position_registry=registry,
            order_repository=(
                persistence.order_repository
            ),
            duplicate_guard=(
                duplicate_guard
            ),
            runtime_id=runtime_id,
            execution_mode=execution_mode,
        )
    )

    # --------------------------------------------------------
    # EOD must see durable unresolved SELL orders in addition
    # to T14 unresolved entries and Dhan broker truth.
    # --------------------------------------------------------

    (
        readiness_provider,
        end_of_day_coordinator,
    ) = build_trading_day_end_of_day(
        scheduler=scheduler,
        entry_runtime=(
            trading_runtime.entry_runtime
        ),
        account_adapter=(
            dhan.account_adapter
        ),
        durable_order_repository=(
            persistence.order_repository
        ),
        runtime_id=runtime_id,
    )

    return PhoenixExitRuntimeContainer(
        persistence=persistence,
        dhan=dhan,
        trading_runtime=(
            trading_runtime
        ),
        exit_persistence=(
            exit_persistence
        ),
        durable_exit_provider=(
            durable_exit_provider
        ),
        duplicate_guard=(
            duplicate_guard
        ),
        exit_plan_builder=(
            exit_plan_builder
        ),
        exit_execution_service=(
            exit_execution_service
        ),
        position_lifecycle_manager=(
            position_lifecycle_manager
        ),
        exit_integration=(
            exit_integration
        ),
        exit_reconciliation=(
            exit_reconciliation
        ),
        force_exit_coordinator=(
            force_exit_coordinator
        ),
        trading_day_force_exit=(
            trading_day_force_exit
        ),
        force_exit_runtime=(
            force_exit_runtime
        ),
        readiness_provider=(
            readiness_provider
        ),
        end_of_day_coordinator=(
            end_of_day_coordinator
        ),
    )


@dataclass(
    frozen=True,
    slots=True,
)
class PhoenixRuntimeStartupContainer:
    """
    Shared M08/M10 startup composition graph.

    Recovery discovery is completed before construction of the
    TradingRuntimeOrchestrator so recovery_required cannot drift
    from persisted Phoenix state.
    """

    persistence: PhoenixPersistenceContainer
    scheduler: TradingDayScheduler
    recovery_service: StartupRecoveryService
    startup_coordinator: TradingDayStartupCoordinator
    recovery_plan: StartupRecoveryPlan
    event_bus: RuntimeEventBus
    orchestrator: TradingRuntimeOrchestrator


def build_runtime_startup_foundation(
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
    Compose Phoenix startup recovery and M08 runtime ownership.

    Safety-critical construction order:

        shared persistence repositories
            ->
        StartupRecoveryService
            ->
        TradingDayStartupCoordinator
            ->
        build recovery plan
            ->
        TradingRuntimeOrchestrator

    This function does NOT start the runtime and does NOT perform
    broker recovery. Broker calls occur only later if the startup
    coordinator starts a recovery-required trading day.
    """

    recovery_service = StartupRecoveryService(
        runtime_repository=(
            persistence.runtime_repository
        ),
        order_repository=(
            persistence.order_repository
        ),
        position_repository=(
            persistence.position_repository
        ),
        broker_provider=broker_provider,
        state_restorer=state_restorer,
    )

    startup_coordinator = (
        TradingDayStartupCoordinator(
            scheduler=scheduler,
            recovery_service=recovery_service,
        )
    )

    # This MUST happen before orchestrator construction.
    recovery_plan = (
        startup_coordinator
        .build_recovery_plan()
    )

    runtime_event_bus = (
        event_bus
        if event_bus is not None
        else RuntimeEventBus()
    )

    orchestrator = (
        TradingRuntimeOrchestrator(
            runtime_id=runtime_id,
            trading_date=scheduler.trading_date,
            mode=mode,
            event_bus=runtime_event_bus,
            created_at=created_at,
            recovery_required=(
                recovery_plan.recovery_required
            ),
        )
    )

    return PhoenixRuntimeStartupContainer(
        persistence=persistence,
        scheduler=scheduler,
        recovery_service=recovery_service,
        startup_coordinator=startup_coordinator,
        recovery_plan=recovery_plan,
        event_bus=runtime_event_bus,
        orchestrator=orchestrator,
    )


def build_trading_day_end_of_day(
    *,
    scheduler: TradingDayScheduler,
    entry_runtime:
        TradingDayEntryRuntimeCoordinator,
    account_adapter: DhanAccountAdapter,
    durable_order_repository:
        SQLAlchemyOrderRepository
        | None = None,
    runtime_id: str | None = None,
) -> tuple[
    TradingDayCloseReadinessProvider,
    TradingDayEndOfDayCoordinator,
]:
    """
    Compose the M10 end-of-day application boundary.

    The exact supplied scheduler, entry runtime and Dhan account
    adapter are preserved.

    This function performs composition only. It does not:
        - start the scheduler,
        - query Dhan,
        - start persistence,
        - evaluate close readiness,
        - transition the trading day.
    """

    readiness_provider = (
        TradingDayCloseReadinessProvider(
            entry_runtime=entry_runtime,
            account_adapter=account_adapter,
            durable_order_repository=(
                durable_order_repository
            ),
            runtime_id=runtime_id,
        )
    )

    end_of_day_coordinator = (
        TradingDayEndOfDayCoordinator(
            scheduler=scheduler,
            readiness_provider=readiness_provider,
        )
    )

    return (
        readiness_provider,
        end_of_day_coordinator,
    )



# ============================================================
# Production crash-restart recovery composition
# ============================================================

from src.app.recovery import (
    PhoenixDhanRecoveryProvider,
    PhoenixRecoveryStateRestorer,
    RecoveryStateRestorerBinding,
)


def build_dhan_recovery_provider(
    *,
    dhan: PhoenixDhanContainer,
) -> PhoenixDhanRecoveryProvider:
    """
    Compose Dhan broker truth from the exact existing Dhan graph.

    No additional SDK client is created.
    """

    if not isinstance(
        dhan,
        PhoenixDhanContainer,
    ):
        raise TypeError(
            "dhan must be PhoenixDhanContainer"
        )

    return PhoenixDhanRecoveryProvider(
        order_adapter=(
            dhan.order_adapter
        ),
        dhan_client=(
            dhan.client
        ),
        account_id=(
            dhan.account_id
        ),
    )


def build_recovery_state_restorer_binding(
) -> RecoveryStateRestorerBinding:
    """
    Create the deferred startup-recovery state-restorer boundary.
    """

    return RecoveryStateRestorerBinding()


def build_recovery_foundation(
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
    Bind the complete production restart-recovery graph.

    Construction only:
        - no broker query,
        - no recovery execution,
        - no BUY,
        - no SELL,
        - no scheduler transition.

    Sequence floors are restored from same-day durable order
    identities while building the concrete state restorer.
    """

    if (
        runtime_startup.persistence
        is not persistence
    ):
        raise ValueError(
            "runtime_startup must share exact persistence"
        )

    if (
        trading_runtime.persistence
        is not persistence
    ):
        raise ValueError(
            "trading_runtime must share exact persistence"
        )

    if (
        trading_runtime.dhan
        is not dhan
    ):
        raise ValueError(
            "trading_runtime must share exact Dhan graph"
        )

    if (
        trading_runtime.runtime_startup
        is not runtime_startup
    ):
        raise ValueError(
            "trading_runtime must share exact runtime startup"
        )

    if (
        exit_runtime.persistence
        is not persistence
    ):
        raise ValueError(
            "exit_runtime must share exact persistence"
        )

    if (
        exit_runtime.dhan
        is not dhan
    ):
        raise ValueError(
            "exit_runtime must share exact Dhan graph"
        )

    if (
        exit_runtime.trading_runtime
        is not trading_runtime
    ):
        raise ValueError(
            "exit_runtime must share exact trading runtime"
        )

    if (
        broker_provider.order_adapter
        is not dhan.order_adapter
    ):
        raise ValueError(
            "recovery provider must use exact Dhan order adapter"
        )

    if (
        broker_provider.dhan_client
        is not dhan.client
    ):
        raise ValueError(
            "recovery provider must use exact Dhan SDK client"
        )

    if (
        broker_provider.account_id
        != dhan.account_id
    ):
        raise ValueError(
            "recovery provider account identity mismatch"
        )

    if (
        runtime_startup
        .recovery_service
        .broker_provider
        is not broker_provider
    ):
        raise ValueError(
            "startup recovery must own exact "
            "production Dhan recovery provider"
        )

    if (
        runtime_startup
        .recovery_service
        .state_restorer
        is not state_restorer_binding
    ):
        raise ValueError(
            "startup recovery must own exact "
            "state-restorer binding"
        )

    if state_restorer_binding.is_bound:
        raise ValueError(
            "state-restorer binding is already bound"
        )

    if (
        exit_runtime.position_lifecycle_manager
        .registry
        is not trading_runtime.position_registry
    ):
        raise ValueError(
            "recovery must share exact PositionRegistry"
        )

    if (
        exit_runtime.duplicate_guard
        is not exit_runtime
        .exit_execution_service
        .duplicate_guard
    ):
        raise ValueError(
            "recovery must share exact exit duplicate guard"
        )

    source_runtime_id = (
        runtime_startup
        .recovery_plan
        .source_runtime_id
    )

    if (
        runtime_startup
        .recovery_plan
        .recovery_required
        and source_runtime_id is None
    ):
        raise RuntimeError(
            "recovery-required startup has no source runtime"
        )

    source_exit_persistence = None

    if source_runtime_id is not None:
        source_exit_persistence = (
            SQLAlchemyExitPersistenceService(
                runtime_id=source_runtime_id,
                order_repository=(
                    persistence.order_repository
                ),
                fill_repository=(
                    persistence.order_fill_repository
                ),
                position_repository=(
                    persistence.position_repository
                ),
            )
        )

    restorer = (
        PhoenixRecoveryStateRestorer(
            source_runtime_id=(
                source_runtime_id
            ),
            trading_date=(
                runtime_startup
                .scheduler
                .trading_date
            ),
            option_selection_repository=(
                persistence
                .option_selection_repository
            ),
            order_repository=(
                persistence.order_repository
            ),
            position_repository=(
                persistence.position_repository
            ),
            execution_service=(
                trading_runtime.execution_service
            ),
            exit_execution_service=(
                exit_runtime
                .exit_execution_service
            ),
            exit_persistence=(
                source_exit_persistence
            ),
            position_registry=(
                trading_runtime.position_registry
            ),
            position_lifecycle_manager=(
                exit_runtime
                .position_lifecycle_manager
            ),
            exit_duplicate_guard=(
                exit_runtime.duplicate_guard
            ),
        )
    )

    state_restorer_binding.bind(
        restorer
    )

    return restorer



__all__ = [
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
]
