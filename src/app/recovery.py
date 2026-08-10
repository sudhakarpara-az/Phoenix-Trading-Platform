"""
Phoenix production crash-restart recovery adapters.

This module bridges the already-defined M08 recovery Protocols
to the existing Dhan, M06, M07 and durable database components.

It does not own:
    - strategy rules,
    - option-selection policy,
    - order-entry policy,
    - scheduler policy,
    - live-order enablement.

Safety rules:

    broker truth
        ->
    durable reconciliation
        ->
    exact existing runtime owners rehydrated

No unresolved BUY is resubmitted during recovery.

Existing SELL orders are reconciled through the durable SELL
persistence boundary and are never blindly resubmitted.
"""

from __future__ import annotations

import re

from datetime import (
    date,
    datetime,
)
from decimal import (
    Decimal,
    InvalidOperation,
)
from math import isclose
from typing import (
    Any,
)

from src.account.account_types import (
    BrokerAccountId,
)
from src.database.exit_durability import (
    SQLAlchemyExitPersistenceService,
)
from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyOptionSelectionRepository,
    SQLAlchemyOrderRepository,
    SQLAlchemyPositionRepository,
)
from src.database.schema import (
    OptionSelectionRecord,
    OrderRecord,
    PositionRecord,
)
from src.execution.dhan_order_adapter import (
    DhanOrderAdapter,
)
from src.execution.execution_service import (
    ExecutionService,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    OrderIntentId,
)
from src.execution.exit_execution_provider import (
    ExitOrderIntent,
    ExitOrderIntentId,
    ExitOrderSnapshot,
    ExitTransactionType,
)
from src.execution.exit_execution_service import (
    ExitExecutionService,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
    IdempotencyKey,
    IdempotencyRecord,
    IdempotencyState,
)
from src.execution.order_state_machine import (
    OrderLifecycleState,
)
from src.execution.position_exit_types import (
    ExitOrderType,
    ExitReason,
    FilledPosition,
    FilledPositionId,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
    SelectedOption,
)
from src.risk.position_lifecycle_manager import (
    PositionLifecycleManager,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionRiskId,
    RiskTriggerType,
    StopLossDefinition,
    StopLossState,
    TargetDefinition,
    TargetState,
)
from src.runtime.recovery_types import (
    BrokerRecoveryOrderSnapshot,
    BrokerRecoveryOrderState,
    BrokerRecoveryPositionSnapshot,
    RecoveryStateRestorer,
)
from src.signals.signal_types import (
    SignalId,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


class PhoenixRecoveryError(
    RuntimeError
):
    """
    Phoenix could not safely reconstruct persisted runtime state.
    """


# ============================================================
# Deferred state-restorer binding
# ============================================================


class RecoveryStateRestorerBinding:
    """
    Deferred RecoveryStateRestorer binding.

    Startup recovery composition is created before the complete
    M06/M07 runtime graph exists.

    This object breaks that construction cycle without introducing
    a fake/no-op recovery implementation.

    Before binding:
        restore_*() fails closed.

    After binding:
        calls are forwarded to the exact concrete production
        PhoenixRecoveryStateRestorer.

    Binding may occur exactly once.
    """

    def __init__(
        self,
    ) -> None:
        self._delegate: (
            RecoveryStateRestorer
            | None
        ) = None

    @property
    def delegate(
        self,
    ) -> (
        RecoveryStateRestorer
        | None
    ):
        return self._delegate

    @property
    def is_bound(
        self,
    ) -> bool:
        return self._delegate is not None

    def bind(
        self,
        delegate: RecoveryStateRestorer,
    ) -> RecoveryStateRestorer:
        if self._delegate is not None:
            raise RuntimeError(
                "recovery state restorer is already bound"
            )

        if not callable(
            getattr(
                delegate,
                "restore_order",
                None,
            )
        ):
            raise TypeError(
                "delegate must implement restore_order"
            )

        if not callable(
            getattr(
                delegate,
                "restore_position",
                None,
            )
        ):
            raise TypeError(
                "delegate must implement restore_position"
            )

        self._delegate = delegate

        return delegate

    def restore_order(
        self,
        *,
        persisted_order: Any,
        broker_snapshot:
            BrokerRecoveryOrderSnapshot,
    ) -> None:
        delegate = self._require_delegate()

        delegate.restore_order(
            persisted_order=persisted_order,
            broker_snapshot=broker_snapshot,
        )

    def restore_position(
        self,
        *,
        persisted_position: Any,
        broker_snapshot:
            BrokerRecoveryPositionSnapshot,
    ) -> None:
        delegate = self._require_delegate()

        delegate.restore_position(
            persisted_position=persisted_position,
            broker_snapshot=broker_snapshot,
        )

    def _require_delegate(
        self,
    ) -> RecoveryStateRestorer:
        delegate = self._delegate

        if delegate is None:
            raise PhoenixRecoveryError(
                "production recovery state restorer "
                "has not been bound"
            )

        return delegate


# ============================================================
# Concrete Dhan broker-truth provider
# ============================================================


class PhoenixDhanRecoveryProvider:
    """
    Concrete Dhan implementation of BrokerRecoveryProvider.

    Order truth is delegated to the exact existing
    DhanOrderAdapter.

    Position truth uses the exact same authenticated Dhan SDK
    client owned by PhoenixDhanContainer.

    No additional Dhan client is constructed here.
    """

    def __init__(
        self,
        *,
        order_adapter: DhanOrderAdapter,
        dhan_client: Any,
        account_id: BrokerAccountId,
    ) -> None:
        if not isinstance(
            order_adapter,
            DhanOrderAdapter,
        ):
            raise TypeError(
                "order_adapter must be DhanOrderAdapter"
            )

        if dhan_client is None:
            raise ValueError(
                "dhan_client cannot be None"
            )

        if not isinstance(
            account_id,
            BrokerAccountId,
        ):
            raise TypeError(
                "account_id must be BrokerAccountId"
            )

        self._order_adapter = (
            order_adapter
        )

        self._dhan_client = (
            dhan_client
        )

        self._account_id = (
            account_id
        )

    @property
    def order_adapter(
        self,
    ) -> DhanOrderAdapter:
        return self._order_adapter

    @property
    def dhan_client(
        self,
    ) -> Any:
        return self._dhan_client

    @property
    def account_id(
        self,
    ) -> BrokerAccountId:
        return self._account_id

    def get_order_snapshot(
        self,
        *,
        broker_order_id: str,
        checked_at: datetime,
    ) -> BrokerRecoveryOrderSnapshot:
        normalized_order_id = (
            broker_order_id.strip()
        )

        if not normalized_order_id:
            raise ValueError(
                "broker_order_id cannot be empty"
            )

        if type(checked_at) is not datetime:
            raise TypeError(
                "checked_at must be a datetime"
            )

        reference = BrokerOrderReference(
            broker_name="DHAN",
            order_id=normalized_order_id,
        )

        snapshot = (
            self._order_adapter
            .get_order_status(
                reference
            )
        )

        state = self._to_recovery_order_state(
            snapshot.status
        )

        return BrokerRecoveryOrderSnapshot(
            broker_order_id=(
                normalized_order_id
            ),
            state=state,
            quantity=snapshot.quantity,
            filled_quantity=(
                snapshot.filled_quantity
            ),
            average_fill_price=(
                snapshot.average_price
            ),
            checked_at=checked_at,
        )

    def get_position_snapshot(
        self,
        *,
        security_id: str,
        checked_at: datetime,
    ) -> BrokerRecoveryPositionSnapshot:
        normalized_security_id = (
            security_id.strip()
        )

        if not normalized_security_id:
            raise ValueError(
                "security_id cannot be empty"
            )

        if type(checked_at) is not datetime:
            raise TypeError(
                "checked_at must be a datetime"
            )

        try:
            response = (
                self._dhan_client
                .get_positions()
            )
        except Exception as exc:
            raise PhoenixRecoveryError(
                "Dhan positions request failed "
                "during startup recovery"
            ) from exc

        positions = self._extract_position_list(
            response
        )

        net_quantity = 0

        for index, item in enumerate(
            positions
        ):
            if not isinstance(
                item,
                dict,
            ):
                raise PhoenixRecoveryError(
                    "Dhan recovery position "
                    f"{index} is not a dictionary"
                )

            response_account_id = (
                self._required_text(
                    item,
                    "dhanClientId",
                )
            )

            if (
                response_account_id
                != self._account_id.value
            ):
                raise PhoenixRecoveryError(
                    "Dhan recovery position account "
                    "does not match configured account"
                )

            item_security_id = (
                self._required_text(
                    item,
                    "securityId",
                )
            )

            item_net_quantity = (
                self._integral_quantity(
                    item.get(
                        "netQty"
                    ),
                    field_name="netQty",
                )
            )

            if (
                item_security_id
                == normalized_security_id
            ):
                net_quantity += (
                    item_net_quantity
                )

        return BrokerRecoveryPositionSnapshot(
            security_id=normalized_security_id,
            net_quantity=net_quantity,
            average_price=None,
            checked_at=checked_at,
        )

    @staticmethod
    def _to_recovery_order_state(
        status: BrokerOrderStatus,
    ) -> BrokerRecoveryOrderState:
        mapping = {
            BrokerOrderStatus.PENDING:
                BrokerRecoveryOrderState.OPEN,
            BrokerOrderStatus.OPEN:
                BrokerRecoveryOrderState.OPEN,
            BrokerOrderStatus.PARTIALLY_FILLED:
                BrokerRecoveryOrderState
                .PARTIALLY_FILLED,
            BrokerOrderStatus.FILLED:
                BrokerRecoveryOrderState.FILLED,
            BrokerOrderStatus.CANCELLED:
                BrokerRecoveryOrderState.CANCELLED,
            BrokerOrderStatus.REJECTED:
                BrokerRecoveryOrderState.REJECTED,
            BrokerOrderStatus.UNKNOWN:
                BrokerRecoveryOrderState.UNKNOWN,
        }

        return mapping.get(
            status,
            BrokerRecoveryOrderState.UNKNOWN,
        )

    @staticmethod
    def _extract_position_list(
        response: Any,
    ) -> list[Any]:
        if isinstance(
            response,
            list,
        ):
            return response

        current = response

        for _ in range(4):
            if not isinstance(
                current,
                dict,
            ):
                raise PhoenixRecoveryError(
                    "Dhan recovery positions response "
                    "has invalid structure"
                )

            status = current.get(
                "status"
            )

            if (
                status is not None
                and str(status).strip().lower()
                not in {
                    "success",
                    "successful",
                }
            ):
                raise PhoenixRecoveryError(
                    "Dhan recovery positions request "
                    "returned unsuccessful status"
                )

            if "data" not in current:
                raise PhoenixRecoveryError(
                    "Dhan recovery positions response "
                    "does not contain a position list"
                )

            data = current[
                "data"
            ]

            if isinstance(
                data,
                list,
            ):
                return data

            if isinstance(
                data,
                dict,
            ):
                current = data
                continue

            raise PhoenixRecoveryError(
                "Dhan recovery positions data "
                "has invalid structure"
            )

        raise PhoenixRecoveryError(
            "Dhan recovery positions response "
            "exceeded supported wrapper depth"
        )

    @staticmethod
    def _required_text(
        item: dict[str, Any],
        key: str,
    ) -> str:
        value = item.get(
            key
        )

        if value is None:
            raise PhoenixRecoveryError(
                "Dhan recovery position "
                f"missing {key}"
            )

        text = str(
            value
        ).strip()

        if not text:
            raise PhoenixRecoveryError(
                "Dhan recovery position "
                f"contains empty {key}"
            )

        return text

    @staticmethod
    def _integral_quantity(
        value: Any,
        *,
        field_name: str,
    ) -> int:
        if value is None:
            raise PhoenixRecoveryError(
                "Dhan recovery position "
                f"missing {field_name}"
            )

        try:
            number = Decimal(
                str(value)
            )
        except (
            InvalidOperation,
            ValueError,
            TypeError,
        ) as exc:
            raise PhoenixRecoveryError(
                "Dhan recovery position "
                f"contains invalid {field_name}"
            ) from exc

        integral = (
            number.to_integral_value()
        )

        if number != integral:
            raise PhoenixRecoveryError(
                "Dhan recovery position "
                f"{field_name} must be integral"
            )

        return int(
            integral
        )


# ============================================================
# Concrete Phoenix state restorer
# ============================================================


class PhoenixRecoveryStateRestorer:
    """
    Rehydrates confirmed durable/broker state into the exact
    existing Phoenix M06/M07 runtime owners.

    BUY recovery:
        - terminal no-fill cancellation/rejection is restored,
        - already-durable FILLED positions may be finalized,
        - unresolved OPEN/PARTIALLY_FILLED BUYs fail closed.

    SELL recovery:
        - rebuild the durable M07 position,
        - checkpoint authoritative broker fill facts,
        - apply only the unapplied fill delta,
        - persist PositionRecord before terminalizing SELL,
        - restore the shared exit idempotency guard.

    No recovery path submits a new broker order.
    """

    _BUY_PATTERN = re.compile(
        r"^ORD-\d{8}-(\d{6})$"
    )

    _SELL_PATTERN = re.compile(
        r"^EXIT-\d{8}-(\d{6})$"
    )

    def __init__(
        self,
        *,
        source_runtime_id: str | None,
        trading_date: date,
        option_selection_repository:
            SQLAlchemyOptionSelectionRepository,
        order_repository:
            SQLAlchemyOrderRepository,
        position_repository:
            SQLAlchemyPositionRepository,
        execution_service:
            ExecutionService,
        exit_execution_service:
            ExitExecutionService,
        exit_persistence:
            SQLAlchemyExitPersistenceService
            | None,
        position_registry:
            PositionRegistry,
        position_lifecycle_manager:
            PositionLifecycleManager,
        exit_duplicate_guard:
            DuplicateOrderGuard,
    ) -> None:
        if (
            source_runtime_id is not None
            and not source_runtime_id.strip()
        ):
            raise ValueError(
                "source_runtime_id cannot be empty"
            )

        if not isinstance(
            trading_date,
            date,
        ):
            raise TypeError(
                "trading_date must be a date"
            )

        if not isinstance(
            execution_service,
            ExecutionService,
        ):
            raise TypeError(
                "execution_service must be ExecutionService"
            )

        if not isinstance(
            exit_execution_service,
            ExitExecutionService,
        ):
            raise TypeError(
                "exit_execution_service must be "
                "ExitExecutionService"
            )

        if not isinstance(
            position_registry,
            PositionRegistry,
        ):
            raise TypeError(
                "position_registry must be PositionRegistry"
            )

        if not isinstance(
            position_lifecycle_manager,
            PositionLifecycleManager,
        ):
            raise TypeError(
                "position_lifecycle_manager must be "
                "PositionLifecycleManager"
            )

        if not isinstance(
            exit_duplicate_guard,
            DuplicateOrderGuard,
        ):
            raise TypeError(
                "exit_duplicate_guard must be "
                "DuplicateOrderGuard"
            )

        if (
            exit_execution_service
            .duplicate_guard
            is not exit_duplicate_guard
        ):
            raise ValueError(
                "exit execution service must share "
                "the exact recovery duplicate guard"
            )

        if (
            position_lifecycle_manager
            .registry
            is not position_registry
        ):
            raise ValueError(
                "position lifecycle manager must share "
                "the exact recovery PositionRegistry"
            )

        normalized_source = (
            source_runtime_id.strip()
            if source_runtime_id
            is not None
            else None
        )

        if (
            normalized_source is not None
            and exit_persistence is None
        ):
            raise ValueError(
                "source runtime recovery requires "
                "source exit persistence"
            )

        if (
            exit_persistence is not None
            and normalized_source is not None
            and exit_persistence.runtime_id
            != normalized_source
        ):
            raise ValueError(
                "recovery exit persistence must be "
                "scoped to source runtime"
            )

        self._source_runtime_id = (
            normalized_source
        )

        self._trading_date = (
            trading_date
        )

        self._option_selection_repository = (
            option_selection_repository
        )

        self._order_repository = (
            order_repository
        )

        self._position_repository = (
            position_repository
        )

        self._execution_service = (
            execution_service
        )

        self._exit_execution_service = (
            exit_execution_service
        )

        self._exit_persistence = (
            exit_persistence
        )

        self._position_registry = (
            position_registry
        )

        self._position_lifecycle_manager = (
            position_lifecycle_manager
        )

        self._exit_duplicate_guard = (
            exit_duplicate_guard
        )

        self._restore_sequence_floors()

    @property
    def source_runtime_id(
        self,
    ) -> str | None:
        return self._source_runtime_id

    @property
    def trading_date(
        self,
    ) -> date:
        return self._trading_date

    @property
    def position_registry(
        self,
    ) -> PositionRegistry:
        return self._position_registry

    # ========================================================
    # RecoveryStateRestorer
    # ========================================================

    def restore_order(
        self,
        *,
        persisted_order: Any,
        broker_snapshot:
            BrokerRecoveryOrderSnapshot,
    ) -> None:
        if not isinstance(
            persisted_order,
            OrderRecord,
        ):
            raise TypeError(
                "persisted_order must be OrderRecord"
            )

        if not isinstance(
            broker_snapshot,
            BrokerRecoveryOrderSnapshot,
        ):
            raise TypeError(
                "broker_snapshot must be "
                "BrokerRecoveryOrderSnapshot"
            )

        self._require_source_runtime(
            persisted_order.runtime_id
        )

        if (
            persisted_order.broker_order_id
            != broker_snapshot
            .broker_order_id
        ):
            raise PhoenixRecoveryError(
                "broker order identity changed "
                "during recovery"
            )

        if (
            persisted_order.quantity
            != broker_snapshot.quantity
        ):
            raise PhoenixRecoveryError(
                "persisted order quantity does not "
                "match broker recovery quantity"
            )

        if (
            persisted_order.side
            == "BUY"
        ):
            self._restore_buy_order(
                persisted_order=(
                    persisted_order
                ),
                broker_snapshot=(
                    broker_snapshot
                ),
            )

            return

        if (
            persisted_order.side
            == "SELL"
        ):
            self._restore_sell_order(
                persisted_order=(
                    persisted_order
                ),
                broker_snapshot=(
                    broker_snapshot
                ),
            )

            return

        raise PhoenixRecoveryError(
            "persisted recovery order has "
            "unsupported side"
        )

    def restore_position(
        self,
        *,
        persisted_position: Any,
        broker_snapshot:
            BrokerRecoveryPositionSnapshot,
    ) -> None:
        if not isinstance(
            persisted_position,
            PositionRecord,
        ):
            raise TypeError(
                "persisted_position must be "
                "PositionRecord"
            )

        if not isinstance(
            broker_snapshot,
            BrokerRecoveryPositionSnapshot,
        ):
            raise TypeError(
                "broker_snapshot must be "
                "BrokerRecoveryPositionSnapshot"
            )

        self._require_source_runtime(
            persisted_position.runtime_id
        )

        if (
            persisted_position.security_id
            != broker_snapshot.security_id
        ):
            raise PhoenixRecoveryError(
                "position security identity changed "
                "during recovery"
            )

        managed = (
            self._rebuild_managed_position(
                persisted_position
            )
        )

        self._register_or_validate(
            managed
        )

    # ========================================================
    # BUY recovery
    # ========================================================

    def _restore_buy_order(
        self,
        *,
        persisted_order: OrderRecord,
        broker_snapshot:
            BrokerRecoveryOrderSnapshot,
    ) -> None:
        if persisted_order.signal_id is None:
            raise PhoenixRecoveryError(
                "BUY recovery requires signal_id"
            )

        if (
            persisted_order.broker_name is None
            or persisted_order
            .broker_name
            .upper()
            != "DHAN"
        ):
            raise PhoenixRecoveryError(
                "BUY recovery requires DHAN "
                "broker identity"
            )

        if (
            broker_snapshot.state
            is BrokerRecoveryOrderState.OPEN
            or broker_snapshot.state
            is BrokerRecoveryOrderState
            .PARTIALLY_FILLED
        ):
            raise PhoenixRecoveryError(
                "unresolved BUY cannot be safely "
                "reconstructed without its original "
                "runtime execution context"
            )

        if (
            broker_snapshot.state
            in {
                BrokerRecoveryOrderState.UNKNOWN,
                BrokerRecoveryOrderState.NOT_FOUND,
            }
        ):
            raise PhoenixRecoveryError(
                "BUY recovery cannot restore "
                "unknown broker state"
            )

        current = (
            self._order_repository
            .require(
                persisted_order
                .order_intent_id
            )
        )

        if current.side != "BUY":
            raise PhoenixRecoveryError(
                "durable BUY identity changed "
                "during recovery"
            )

        updated_at = max(
            current.updated_at,
            broker_snapshot.checked_at,
        )

        if (
            broker_snapshot.state
            is BrokerRecoveryOrderState
            .CANCELLED
        ):
            if (
                broker_snapshot
                .filled_quantity
                != 0
            ):
                raise PhoenixRecoveryError(
                    "cancelled BUY with broker fill "
                    "requires unresolved entry context"
                )

            current.status = (
                OrderLifecycleState
                .CANCELLED
                .value
            )

            current.filled_quantity = 0
            current.average_fill_price = None
            current.updated_at = updated_at

            self._order_repository.update(
                current
            )

            self._restore_buy_runtime_state(
                order=current,
                lifecycle_state=(
                    OrderLifecycleState
                    .CANCELLED
                ),
                guard_state=(
                    IdempotencyState.RELEASED
                ),
                updated_at=updated_at,
            )

            return

        if (
            broker_snapshot.state
            is BrokerRecoveryOrderState
            .REJECTED
        ):
            if (
                broker_snapshot
                .filled_quantity
                != 0
            ):
                raise PhoenixRecoveryError(
                    "rejected BUY cannot contain "
                    "broker fills"
                )

            current.status = (
                OrderLifecycleState
                .REJECTED
                .value
            )

            current.filled_quantity = 0
            current.average_fill_price = None
            current.updated_at = updated_at

            self._order_repository.update(
                current
            )

            self._restore_buy_runtime_state(
                order=current,
                lifecycle_state=(
                    OrderLifecycleState
                    .REJECTED
                ),
                guard_state=(
                    IdempotencyState.COMPLETED
                ),
                updated_at=updated_at,
            )

            return

        if (
            broker_snapshot.state
            is not BrokerRecoveryOrderState
            .FILLED
        ):
            raise PhoenixRecoveryError(
                "unsupported BUY recovery state"
            )

        if (
            broker_snapshot.filled_quantity
            != current.quantity
        ):
            raise PhoenixRecoveryError(
                "FILLED BUY must have full "
                "broker quantity"
            )

        average_fill_price = (
            broker_snapshot
            .average_fill_price
        )

        if (
            average_fill_price is None
            or average_fill_price <= 0
        ):
            raise PhoenixRecoveryError(
                "FILLED BUY requires positive "
                "broker average fill price"
            )

        position = (
            self._position_repository
            .get_by_entry_order_intent_id(
                current.order_intent_id
            )
        )

        if position is None:
            raise PhoenixRecoveryError(
                "FILLED BUY has no durable "
                "PositionRecord; refusing to guess "
                "missing M07 state"
            )

        if (
            position.original_quantity
            != broker_snapshot
            .filled_quantity
        ):
            raise PhoenixRecoveryError(
                "FILLED BUY quantity conflicts "
                "with durable PositionRecord"
            )

        if not isclose(
            position.entry_price,
            average_fill_price,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise PhoenixRecoveryError(
                "FILLED BUY average price conflicts "
                "with durable PositionRecord"
            )

        if (
            current.position_id is not None
            and current.position_id
            != position.position_id
        ):
            raise PhoenixRecoveryError(
                "FILLED BUY position identity "
                "conflicts with durable order"
            )

        current.position_id = (
            position.position_id
        )

        current.status = (
            OrderLifecycleState
            .FILLED
            .value
        )

        current.filled_quantity = (
            broker_snapshot
            .filled_quantity
        )

        current.average_fill_price = (
            average_fill_price
        )

        current.updated_at = (
            updated_at
        )

        self._order_repository.update(
            current
        )

        self._restore_buy_runtime_state(
            order=current,
            lifecycle_state=(
                OrderLifecycleState.FILLED
            ),
            guard_state=(
                IdempotencyState.COMPLETED
            ),
            updated_at=updated_at,
        )

    def _restore_buy_runtime_state(
        self,
        *,
        order: OrderRecord,
        lifecycle_state:
            OrderLifecycleState,
        guard_state:
            IdempotencyState,
        updated_at: datetime,
    ) -> None:
        signal_id_text = (
            order.signal_id
        )

        if signal_id_text is None:
            raise PhoenixRecoveryError(
                "BUY runtime restoration "
                "requires signal_id"
            )

        intent_id = OrderIntentId(
            order.order_intent_id
        )

        self._execution_service\
            .order_state_machine\
            .restore_state(
                intent_id=intent_id,
                current_state=(
                    lifecycle_state
                ),
                created_at=order.created_at,
                updated_at=updated_at,
            )

        signal_id = SignalId(
            signal_id_text
        )

        key = (
            IdempotencyKey
            .from_signal_id(
                signal_id
            )
        )

        self._execution_service\
            .idempotency_guard\
            .restore_record(
                IdempotencyRecord(
                    key=key,
                    state=guard_state,
                    intent_id=(
                        order.order_intent_id
                    ),
                    created_at=(
                        order.created_at
                    ),
                    updated_at=updated_at,
                )
            )

    # ========================================================
    # SELL recovery
    # ========================================================

    def _restore_sell_order(
        self,
        *,
        persisted_order: OrderRecord,
        broker_snapshot:
            BrokerRecoveryOrderSnapshot,
    ) -> None:
        if persisted_order.position_id is None:
            raise PhoenixRecoveryError(
                "SELL recovery requires position_id"
            )

        if persisted_order.reason is None:
            raise PhoenixRecoveryError(
                "SELL recovery requires exit reason"
            )

        if (
            persisted_order.broker_name is None
            or persisted_order
            .broker_name
            .upper()
            != "DHAN"
        ):
            raise PhoenixRecoveryError(
                "SELL recovery requires DHAN "
                "broker identity"
            )

        if (
            broker_snapshot.state
            in {
                BrokerRecoveryOrderState.UNKNOWN,
                BrokerRecoveryOrderState.NOT_FOUND,
            }
        ):
            raise PhoenixRecoveryError(
                "SELL recovery cannot restore "
                "unknown broker state"
            )

        if (
            broker_snapshot.state
            is BrokerRecoveryOrderState
            .REJECTED
            and broker_snapshot
            .filled_quantity
            != 0
        ):
            raise PhoenixRecoveryError(
                "rejected SELL cannot contain "
                "broker fills"
            )

        if (
            broker_snapshot.state
            is BrokerRecoveryOrderState
            .FILLED
            and broker_snapshot
            .filled_quantity
            != persisted_order.quantity
        ):
            raise PhoenixRecoveryError(
                "FILLED SELL must have full "
                "broker quantity"
            )

        position_record = (
            self._position_repository
            .require(
                persisted_order
                .position_id
            )
        )

        self._require_source_runtime(
            position_record.runtime_id
        )

        managed = (
            self._rebuild_managed_position(
                position_record
            )
        )

        managed = (
            self._register_or_validate(
                managed
            )
        )

        intent = (
            self._reconstruct_exit_intent(
                persisted_order,
                managed,
            )
        )

        exit_persistence = (
            self._require_exit_persistence()
        )

        exit_snapshot = (
            self._to_exit_order_snapshot(
                persisted_order=(
                    persisted_order
                ),
                broker_snapshot=(
                    broker_snapshot
                ),
            )
        )

        # Durable fill ledger FIRST.
        delta = (
            exit_persistence
            .checkpoint_broker_snapshot(
                intent=intent,
                snapshot=exit_snapshot,
            )
        )

        # Active SELL must own EXIT_PENDING state before
        # applying an exit fill.
        if (
            managed.open_quantity > 0
            and managed.state
            in {
                ManagedPositionState.OPEN,
                ManagedPositionState
                .PARTIALLY_EXITED,
            }
        ):
            managed = (
                self._position_lifecycle_manager
                .mark_exit_pending(
                    position_id=(
                        intent.position_id
                    ),
                    trigger=(
                        RiskTriggerType(
                            intent.reason.value
                        )
                    ),
                    changed_at=max(
                        managed.updated_at,
                        broker_snapshot.checked_at,
                    ),
                )
            )

        if delta.has_fill:
            if delta.price is None:
                raise PhoenixRecoveryError(
                    "positive recovered SELL fill "
                    "has no price"
                )

            managed = (
                self._position_lifecycle_manager
                .apply_exit_fill(
                    position_id=(
                        intent.position_id
                    ),
                    fill_quantity=(
                        delta.quantity
                    ),
                    fill_price=(
                        delta.price
                    ),
                    filled_at=max(
                        managed.updated_at,
                        delta.filled_at,
                    ),
                )
            )

        state = (
            broker_snapshot.state
        )

        if (
            state
            in {
                BrokerRecoveryOrderState.OPEN,
                BrokerRecoveryOrderState
                .PARTIALLY_FILLED,
            }
        ):
            if managed.open_quantity <= 0:
                raise PhoenixRecoveryError(
                    "active SELL broker state "
                    "cannot own closed position"
                )

            if (
                managed.state
                in {
                    ManagedPositionState.OPEN,
                    ManagedPositionState
                    .PARTIALLY_EXITED,
                }
            ):
                managed = (
                    self._position_lifecycle_manager
                    .mark_exit_pending(
                        position_id=(
                            intent.position_id
                        ),
                        trigger=(
                            RiskTriggerType(
                                intent.reason.value
                            )
                        ),
                        changed_at=max(
                            managed.updated_at,
                            broker_snapshot
                            .checked_at,
                        ),
                    )
                )

        elif (
            state
            is BrokerRecoveryOrderState
            .FILLED
        ):
            if managed.open_quantity != 0:
                raise PhoenixRecoveryError(
                    "FILLED SELL did not close "
                    "the durable position"
                )

        elif (
            state
            in {
                BrokerRecoveryOrderState
                .CANCELLED,
                BrokerRecoveryOrderState
                .REJECTED,
            }
        ):
            if (
                managed.open_quantity > 0
                and managed.state
                in {
                    ManagedPositionState
                    .EXIT_PENDING,
                    ManagedPositionState
                    .RECONCILIATION_REQUIRED,
                }
            ):
                managed = (
                    self._position_lifecycle_manager
                    .restore_after_reconciliation(
                        position_id=(
                            intent.position_id
                        ),
                        changed_at=max(
                            managed.updated_at,
                            broker_snapshot
                            .checked_at,
                        ),
                    )
                )

        else:
            raise PhoenixRecoveryError(
                "unsupported SELL recovery state"
            )

        # PositionRecord before terminal SELL OrderRecord.
        exit_persistence\
            .persist_managed_position_after_snapshot(
                intent=intent,
                snapshot=exit_snapshot,
                managed_position=managed,
            )

        self._restore_sell_guard(
            order=persisted_order,
            broker_snapshot=(
                broker_snapshot
            ),
        )

    def _restore_sell_guard(
        self,
        *,
        order: OrderRecord,
        broker_snapshot:
            BrokerRecoveryOrderSnapshot,
    ) -> None:
        if order.position_id is None:
            raise PhoenixRecoveryError(
                "SELL guard recovery requires "
                "position_id"
            )

        if (
            broker_snapshot.state
            in {
                BrokerRecoveryOrderState.OPEN,
                BrokerRecoveryOrderState
                .PARTIALLY_FILLED,
            }
        ):
            guard_state = (
                IdempotencyState.SUBMITTED
            )

        elif (
            broker_snapshot.state
            is BrokerRecoveryOrderState
            .FILLED
        ):
            guard_state = (
                IdempotencyState.COMPLETED
            )

        elif (
            broker_snapshot.state
            in {
                BrokerRecoveryOrderState
                .CANCELLED,
                BrokerRecoveryOrderState
                .REJECTED,
            }
        ):
            guard_state = (
                IdempotencyState.RELEASED
            )

        else:
            raise PhoenixRecoveryError(
                "SELL guard cannot restore "
                "unknown broker state"
            )

        key = IdempotencyKey(
            value=(
                "EXIT_POSITION:"
                f"{order.position_id}"
            )
        )

        self._exit_duplicate_guard\
            .restore_record(
                IdempotencyRecord(
                    key=key,
                    state=guard_state,
                    intent_id=(
                        order.order_intent_id
                    ),
                    created_at=(
                        order.created_at
                    ),
                    updated_at=max(
                        order.updated_at,
                        broker_snapshot.checked_at,
                    ),
                )
            )

    # ========================================================
    # Durable M07 reconstruction
    # ========================================================

    def _rebuild_managed_position(
        self,
        record: PositionRecord,
    ) -> ManagedPosition:
        selection = (
            self._option_selection_repository
            .get_by_signal(
                record.signal_id
            )
        )

        if selection is None:
            raise PhoenixRecoveryError(
                "PositionRecord has no durable "
                "OptionSelectionRecord"
            )

        entry_order = (
            self._order_repository.get(
                record.entry_order_intent_id
            )
        )

        if entry_order is None:
            raise PhoenixRecoveryError(
                "PositionRecord has no durable "
                "entry OrderRecord"
            )

        if entry_order.side != "BUY":
            raise PhoenixRecoveryError(
                "PositionRecord entry order "
                "is not BUY"
            )

        if (
            entry_order.broker_name is None
            or entry_order
            .broker_order_id
            is None
        ):
            raise PhoenixRecoveryError(
                "PositionRecord entry order "
                "has no broker reference"
            )

        if (
            entry_order.signal_id
            != record.signal_id
        ):
            raise PhoenixRecoveryError(
                "PositionRecord signal identity "
                "conflicts with entry order"
            )

        if (
            entry_order.security_id
            != record.security_id
            or entry_order.symbol
            != record.symbol
        ):
            raise PhoenixRecoveryError(
                "PositionRecord contract identity "
                "conflicts with entry order"
            )

        selected_option = (
            self._rebuild_selected_option(
                selection
            )
        )

        if (
            selected_option.security_id
            != record.security_id
            or selected_option.symbol
            != record.symbol
            or selected_option
            .option_type
            .value
            != record.option_type
        ):
            raise PhoenixRecoveryError(
                "PositionRecord contract identity "
                "conflicts with option selection"
            )

        filled_position = FilledPosition(
            position_id=FilledPositionId(
                record.position_id
            ),
            signal_id=SignalId(
                record.signal_id
            ),
            entry_intent_id=OrderIntentId(
                record.entry_order_intent_id
            ),
            entry_broker_reference=(
                BrokerOrderReference(
                    broker_name=(
                        entry_order
                        .broker_name
                    ),
                    order_id=(
                        entry_order
                        .broker_order_id
                    ),
                )
            ),
            selected_option=selected_option,
            level=EntryLevel(
                record.level
            ),
            quantity=(
                record.original_quantity
            ),
            entry_price=(
                record.entry_price
            ),
            filled_at=(
                record.opened_at
            ),
        )

        stop_loss = (
            self._rebuild_stop_loss(
                record
            )
        )

        target = (
            self._rebuild_target(
                record
            )
        )

        return ManagedPosition(
            risk_id=PositionRiskId(
                record.risk_id
            ),
            position=filled_position,
            open_quantity=(
                record.open_quantity
            ),
            closed_quantity=(
                record.closed_quantity
            ),
            realized_pnl=(
                record.realized_pnl
            ),
            state=ManagedPositionState(
                record.state
            ),
            stop_loss=stop_loss,
            target=target,
            created_at=(
                record.opened_at
            ),
            updated_at=(
                record.updated_at
            ),
        )

    @staticmethod
    def _rebuild_selected_option(
        record: OptionSelectionRecord,
    ) -> SelectedOption:
        observed_at = (
            record.quote_received_at
            or record.selected_at
        )

        return SelectedOption(
            candidate=OptionCandidate(
                contract=OptionContract(
                    underlying_symbol=(
                        record
                        .underlying_symbol
                    ),
                    symbol=record.symbol,
                    security_id=(
                        record.security_id
                    ),
                    option_type=OptionType(
                        record.option_type
                    ),
                    strike=record.strike,
                    expiry=record.expiry,
                    lot_size=(
                        record.lot_size
                    ),
                ),
                quote=OptionQuote(
                    ltp=record.ltp,
                    bid=record.bid,
                    ask=record.ask,
                    volume=record.volume,
                    open_interest=(
                        record.open_interest
                    ),
                    received_at=(
                        observed_at
                    ),
                ),
                greeks=OptionGreeks(
                    delta=record.delta,
                    calculated_at=(
                        observed_at
                    ),
                ),
            ),
            selected_at=(
                record.selected_at
            ),
            selection_delta_target=(
                record.target_delta
            ),
        )

    @staticmethod
    @staticmethod
    def _rebuild_stop_loss(
        record: PositionRecord,
    ) -> StopLossDefinition | None:
        stop_price = (
            record.stop_price
        )

        risk_points = (
            record.stop_risk_points
        )

        state_value = (
            record.stop_state
        )

        if (
            stop_price is None
            and risk_points is None
            and (
                state_value is None
                or state_value
                == StopLossState
                .NOT_CONFIGURED
                .value
            )
        ):
            return None

        if (
            stop_price is None
            or risk_points is None
            or state_value is None
        ):
            raise PhoenixRecoveryError(
                "PositionRecord contains partial "
                "stop-loss durability"
            )

        return StopLossDefinition(
            stop_price=stop_price,
            risk_points=risk_points,
            state=StopLossState(
                state_value
            ),
        )

    @staticmethod
    @staticmethod
    def _rebuild_target(
        record: PositionRecord,
    ) -> TargetDefinition | None:
        executable_price = (
            record.executable_target_price
        )

        mapped_target_price = (
            record.mapped_target_price
        )

        booking_zone_start = (
            record.booking_zone_start
        )

        booking_zone_end = (
            record.booking_zone_end
        )

        state_value = (
            record.target_state
        )

        if (
            executable_price is None
            and mapped_target_price is None
            and booking_zone_start is None
            and booking_zone_end is None
            and (
                state_value is None
                or state_value
                == TargetState
                .NOT_CONFIGURED
                .value
            )
        ):
            return None

        if (
            executable_price is None
            or mapped_target_price is None
            or booking_zone_start is None
            or booking_zone_end is None
            or state_value is None
        ):
            raise PhoenixRecoveryError(
                "PositionRecord contains partial "
                "target durability"
            )

        return TargetDefinition(
            executable_price=(
                executable_price
            ),
            mapped_target_price=(
                mapped_target_price
            ),
            booking_zone_start=(
                booking_zone_start
            ),
            booking_zone_end=(
                booking_zone_end
            ),
            state=TargetState(
                state_value
            ),
        )

    def _register_or_validate(
        self,
        managed: ManagedPosition,
    ) -> ManagedPosition:
        matching = tuple(
            existing
            for existing
            in self._position_registry.all()
            if (
                existing
                .position
                .position_id
                .value
                == managed
                .position
                .position_id
                .value
            )
        )

        if not matching:
            return (
                self._position_registry
                .register(
                    managed
                )
            )

        if len(matching) != 1:
            raise PhoenixRecoveryError(
                "PositionRegistry contains duplicate "
                "recovery identity"
            )

        existing = matching[
            0
        ]

        if existing != managed:
            raise PhoenixRecoveryError(
                "PositionRegistry recovery state "
                "conflicts with durable PositionRecord"
            )

        return existing

    # ========================================================
    # SELL conversion
    # ========================================================

    @staticmethod
    def _reconstruct_exit_intent(
        order: OrderRecord,
        position: ManagedPosition,
    ) -> ExitOrderIntent:
        if order.position_id is None:
            raise PhoenixRecoveryError(
                "SELL order has no position_id"
            )

        if order.reason is None:
            raise PhoenixRecoveryError(
                "SELL order has no exit reason"
            )

        return ExitOrderIntent(
            intent_id=ExitOrderIntentId(
                order.order_intent_id
            ),
            position_id=FilledPositionId(
                order.position_id
            ),
            security_id=(
                order.security_id
            ),
            symbol=order.symbol,
            option_type=(
                position
                .position
                .option_type
            ),
            transaction_type=(
                ExitTransactionType.SELL
            ),
            order_type=ExitOrderType(
                order.order_type
            ),
            quantity=order.quantity,
            price=order.limit_price,
            reason=ExitReason(
                order.reason
            ),
            created_at=(
                order.created_at
            ),
        )

    @staticmethod
    def _to_exit_order_snapshot(
        *,
        persisted_order: OrderRecord,
        broker_snapshot:
            BrokerRecoveryOrderSnapshot,
    ) -> ExitOrderSnapshot:
        if (
            persisted_order.broker_name
            is None
            or persisted_order
            .broker_order_id
            is None
        ):
            raise PhoenixRecoveryError(
                "SELL recovery requires "
                "broker reference"
            )

        status_map = {
            BrokerRecoveryOrderState.OPEN:
                BrokerOrderStatus.OPEN,
            BrokerRecoveryOrderState
            .PARTIALLY_FILLED:
                BrokerOrderStatus
                .PARTIALLY_FILLED,
            BrokerRecoveryOrderState.FILLED:
                BrokerOrderStatus.FILLED,
            BrokerRecoveryOrderState.CANCELLED:
                BrokerOrderStatus.CANCELLED,
            BrokerRecoveryOrderState.REJECTED:
                BrokerOrderStatus.REJECTED,
        }

        status = status_map.get(
            broker_snapshot.state
        )

        if status is None:
            raise PhoenixRecoveryError(
                "cannot convert unknown recovery "
                "SELL state"
            )

        return ExitOrderSnapshot(
            broker_reference=(
                BrokerOrderReference(
                    broker_name=(
                        persisted_order
                        .broker_name
                    ),
                    order_id=(
                        persisted_order
                        .broker_order_id
                    ),
                )
            ),
            status=status,
            quantity=(
                broker_snapshot.quantity
            ),
            filled_quantity=(
                broker_snapshot
                .filled_quantity
            ),
            average_price=(
                broker_snapshot
                .average_fill_price
            ),
            updated_at=(
                broker_snapshot.checked_at
            ),
        )

    # ========================================================
    # Sequence recovery
    # ========================================================

    def _restore_sequence_floors(
        self,
    ) -> None:
        orders = (
            self._order_repository
            .list_by_trading_date(
                self._trading_date
            )
        )

        buy_floor = 0
        sell_floor = 0

        for order in orders:
            buy_match = (
                self._BUY_PATTERN.match(
                    order.order_intent_id
                )
            )

            if buy_match is not None:
                buy_floor = max(
                    buy_floor,
                    int(
                        buy_match.group(
                            1
                        )
                    ),
                )

            sell_match = (
                self._SELL_PATTERN.match(
                    order.order_intent_id
                )
            )

            if sell_match is not None:
                sell_floor = max(
                    sell_floor,
                    int(
                        sell_match.group(
                            1
                        )
                    ),
                )

        self._execution_service\
            .restore_sequence_floor(
                buy_floor
            )

        self._exit_execution_service\
            .restore_sequence_floor(
                sell_floor
            )

    # ========================================================
    # Shared validation
    # ========================================================

    def _require_source_runtime(
        self,
        runtime_id: str,
    ) -> None:
        source = (
            self._source_runtime_id
        )

        if source is None:
            raise PhoenixRecoveryError(
                "recovery was invoked without "
                "a source runtime"
            )

        if runtime_id != source:
            raise PhoenixRecoveryError(
                "recovery record does not belong "
                "to configured source runtime"
            )

    def _require_exit_persistence(
        self,
    ) -> SQLAlchemyExitPersistenceService:
        value = (
            self._exit_persistence
        )

        if value is None:
            raise PhoenixRecoveryError(
                "SELL recovery has no source-runtime "
                "exit persistence boundary"
            )

        return value


__all__ = [
    "PhoenixDhanRecoveryProvider",
    "PhoenixRecoveryError",
    "PhoenixRecoveryStateRestorer",
    "RecoveryStateRestorerBinding",
]
