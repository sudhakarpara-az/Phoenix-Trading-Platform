"""
Phoenix durable entry-execution boundary.

M08 persistence integration for the active M10 -> M09 -> M06
entry path.

Safety invariant:

    Signal + selected option + SUBMITTED order state must become
    durable BEFORE BrokerExecutionProvider.submit_order() is
    allowed to cross the real broker boundary.

If persistence fails, the broker call is never made.

If a durable order for the same OrderIntent already exists,
resubmission is blocked fail-closed.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.database.schema import (
    OptionSelectionRecord,
    OrderRecord,
    PositionRecord,
    SignalRecord,
)
from src.execution.broker_execution_provider import (
    BrokerCancellationResult,
    BrokerExecutionProvider,
    BrokerOrderSnapshot,
)
from src.execution.execution_types import (
    BrokerOrderStatus,
    ExecutionResult,
    OrderIntent,
)
from src.execution.order_state_machine import (
    OrderLifecycleState,
    OrderStateMachine,
    OrderStateSnapshot,
)
from src.risk.risk_types import (
    ManagedPosition,
)


class TradingStatePersistenceError(
    RuntimeError
):
    """
    Durable trading-state persistence failed validation.
    """


class _RepositoryPort(
    Protocol,
):
    def add(
        self,
        record: Any,
    ) -> Any:
        ...

    def get(
        self,
        identity: str,
    ) -> Any | None:
        ...

    def update(
        self,
        record: Any,
    ) -> Any:
        ...


class SQLAlchemyEntryPersistenceService:
    """
    Translate active Phoenix M04/M05/M06 entry state into the
    existing M08 SQLAlchemy persistence records.

    Repository implementations continue to own transaction
    boundaries. This service owns only deterministic domain ->
    persistence mapping and fail-closed identity validation.
    """

    def __init__(
        self,
        *,
        runtime_id: str,
        signal_repository: _RepositoryPort,
        option_selection_repository:
            _RepositoryPort,
        order_repository: _RepositoryPort,
        position_repository:
            _RepositoryPort | None = None,
    ) -> None:
        if not isinstance(
            runtime_id,
            str,
        ):
            raise TypeError(
                "runtime_id must be str"
            )

        normalized_runtime_id = (
            runtime_id.strip()
        )

        if not normalized_runtime_id:
            raise ValueError(
                "runtime_id cannot be empty"
            )

        self._runtime_id = (
            normalized_runtime_id
        )

        self._signal_repository = (
            signal_repository
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

    @property
    def runtime_id(
        self,
    ) -> str:
        return self._runtime_id

    def persist_pre_broker_submission(
        self,
        *,
        intent: OrderIntent,
        broker_name: str,
        lifecycle_snapshot:
            OrderStateSnapshot,
    ) -> None:
        """
        Durably establish the entry identity before broker I/O.

        Required state:
            M06 OrderStateMachine == SUBMITTED

        Ordering:
            SignalRecord
                ->
            OptionSelectionRecord
                ->
            OrderRecord(SUBMITTED)
                ->
            broker call may proceed

        Signal and option records may already exist if they were
        persisted earlier in the application lifecycle, but they
        must match exactly.

        An existing OrderRecord always blocks resubmission.
        """

        if not isinstance(
            intent,
            OrderIntent,
        ):
            raise TypeError(
                "intent must be OrderIntent"
            )

        if not isinstance(
            lifecycle_snapshot,
            OrderStateSnapshot,
        ):
            raise TypeError(
                "lifecycle_snapshot must be "
                "OrderStateSnapshot"
            )

        if not isinstance(
            broker_name,
            str,
        ):
            raise TypeError(
                "broker_name must be str"
            )

        normalized_broker_name = (
            broker_name.strip()
        )

        if not normalized_broker_name:
            raise ValueError(
                "broker_name cannot be empty"
            )

        if (
            lifecycle_snapshot.intent_id
            != intent.intent_id
        ):
            raise TradingStatePersistenceError(
                "order lifecycle snapshot does not "
                "belong to supplied intent"
            )

        if (
            lifecycle_snapshot.current_state
            is not OrderLifecycleState.SUBMITTED
        ):
            raise TradingStatePersistenceError(
                "broker submission requires durable "
                "SUBMITTED order lifecycle"
            )

        signal = intent.signal
        selected_option = (
            intent.selected_option
        )

        signal_record = SignalRecord(
            signal_id=(
                signal.signal_id.value
            ),
            runtime_id=self._runtime_id,
            trading_date=(
                signal.trading_date
            ),
            level=signal.level.value,
            signal_type=(
                f"BUY_{signal.direction.value}"
            ),
            option_type=(
                signal.direction.value
            ),
            underlying_price=(
                signal.underlying_price
            ),
            quantity=intent.quantity,
            status=signal.state.value,
            reason=signal.reason.value,
            created_at=(
                signal.generated_at
            ),
            updated_at=(
                signal.generated_at
            ),
        )

        selection_record = (
            OptionSelectionRecord(
                # SelectedOption intentionally has no
                # separate persistence identity. Phoenix has
                # one fixed selected contract per signal here,
                # so the stable signal identity is reused.
                selection_id=(
                    signal.signal_id.value
                ),
                runtime_id=self._runtime_id,
                signal_id=(
                    signal.signal_id.value
                ),
                underlying_symbol=(
                    selected_option
                    .contract
                    .underlying_symbol
                ),
                symbol=(
                    selected_option.symbol
                ),
                security_id=(
                    selected_option.security_id
                ),
                option_type=(
                    selected_option
                    .option_type
                    .value
                ),
                strike=(
                    selected_option.strike
                ),
                expiry=(
                    selected_option.expiry
                ),
                lot_size=(
                    selected_option.lot_size
                ),
                ltp=(
                    selected_option.ltp
                ),
                delta=(
                    selected_option.delta
                ),
                target_delta=(
                    selected_option
                    .selection_delta_target
                ),
                bid=(
                    selected_option
                    .candidate
                    .quote
                    .bid
                ),
                ask=(
                    selected_option
                    .candidate
                    .quote
                    .ask
                ),
                volume=(
                    selected_option
                    .candidate
                    .quote
                    .volume
                ),
                open_interest=(
                    selected_option
                    .candidate
                    .quote
                    .open_interest
                ),
                quote_received_at=(
                    selected_option
                    .candidate
                    .quote
                    .received_at
                ),
                selected_at=(
                    selected_option
                    .selected_at
                ),
            )
        )

        order_record = OrderRecord(
            order_intent_id=(
                intent.intent_id.value
            ),
            runtime_id=self._runtime_id,
            signal_id=(
                signal.signal_id.value
            ),
            position_id=None,
            security_id=(
                selected_option.security_id
            ),
            symbol=(
                selected_option.symbol
            ),
            side=(
                intent.transaction_type.value
            ),
            order_type=(
                intent.order_type.value
            ),
            reason="ENTRY",
            quantity=intent.quantity,
            limit_price=(
                intent.limit_price
            ),
            execution_mode=(
                intent.execution_mode.value
            ),
            status=(
                lifecycle_snapshot
                .current_state
                .value
            ),
            broker_name=(
                normalized_broker_name
            ),
            broker_order_id=None,
            filled_quantity=0,
            average_fill_price=None,
            created_at=(
                intent.created_at
            ),
            submitted_at=(
                lifecycle_snapshot
                .updated_at
            ),
            updated_at=(
                lifecycle_snapshot
                .updated_at
            ),
        )

        self._add_or_validate_signal(
            signal_record
        )

        self._add_or_validate_selection(
            selection_record
        )

        existing_order = (
            self._order_repository.get(
                intent.intent_id.value
            )
        )

        if existing_order is not None:
            raise TradingStatePersistenceError(
                "durable order intent already exists; "
                "broker resubmission blocked: "
                f"{intent.intent_id.value}"
            )

        self._order_repository.add(
            order_record
        )

    def persist_broker_execution_result(
        self,
        *,
        intent: OrderIntent,
        result: ExecutionResult,
        broker_snapshot:
            BrokerOrderSnapshot | None = None,
        lifecycle_snapshot:
            OrderStateSnapshot | None = None,
        managed_position:
            ManagedPosition | None = None,
        terminalize_order: bool = False,
    ) -> None:
        """
        Persist broker acknowledgement and, after M06 proves a
        full fill, checkpoint authoritative fill facts.

        Initial broker-return phase:

            durable OrderRecord already exists as SUBMITTED
                ->
            persist broker acknowledgement/reference only

        Proven-fill phase:

            M06 lifecycle == FILLED
                ->
            broker snapshot == FILLED
                ->
            persist filled_quantity + average_fill_price

        Critically, this method does NOT mark the durable
        OrderRecord FILLED during the proven-fill phase.

        PositionRecord durability must be established first
        because the SQLAlchemy repositories commit independently
        and FILLED is terminal for recovery queries.
        """

        if not isinstance(
            intent,
            OrderIntent,
        ):
            raise TypeError(
                "intent must be OrderIntent"
            )

        if not isinstance(
            result,
            ExecutionResult,
        ):
            raise TypeError(
                "result must be ExecutionResult"
            )

        if (
            broker_snapshot is not None
            and not isinstance(
                broker_snapshot,
                BrokerOrderSnapshot,
            )
        ):
            raise TypeError(
                "broker_snapshot must be "
                "BrokerOrderSnapshot"
            )

        if (
            lifecycle_snapshot is not None
            and not isinstance(
                lifecycle_snapshot,
                OrderStateSnapshot,
            )
        ):
            raise TypeError(
                "lifecycle_snapshot must be "
                "OrderStateSnapshot"
            )

        if type(terminalize_order) is not bool:
            raise TypeError(
                "terminalize_order must be bool"
            )

        if (
            terminalize_order
            and managed_position is None
        ):
            raise TypeError(
                "terminalize_order requires "
                "managed_position"
            )

        if (
            managed_position is not None
            and not isinstance(
                managed_position,
                ManagedPosition,
            )
        ):
            raise TypeError(
                "managed_position must be "
                "ManagedPosition"
            )

        if (
            (broker_snapshot is None)
            != (lifecycle_snapshot is None)
        ):
            raise TypeError(
                "broker_snapshot and lifecycle_snapshot "
                "must be supplied together"
            )

        if (
            managed_position is not None
            and broker_snapshot is None
        ):
            raise TypeError(
                "managed_position requires "
                "broker_snapshot and lifecycle_snapshot"
            )

        if (
            result.intent_id
            != intent.intent_id
        ):
            raise TradingStatePersistenceError(
                "execution result does not belong "
                "to supplied order intent"
            )

        existing = (
            self._order_repository.get(
                intent.intent_id.value
            )
        )

        if existing is None:
            raise TradingStatePersistenceError(
                "broker result cannot be persisted "
                "before durable order intent exists"
            )

        reference = (
            result.broker_reference
        )

        if reference is not None:
            if (
                existing.broker_name
                and existing.broker_name
                != reference.broker_name
            ):
                raise TradingStatePersistenceError(
                    "broker acknowledgement identity "
                    "conflicts with durable order"
                )

            if (
                existing.broker_order_id
                and existing.broker_order_id
                != reference.order_id
            ):
                raise TradingStatePersistenceError(
                    "broker order identity conflicts "
                    "with durable order"
                )

            existing.broker_name = (
                reference.broker_name
            )

            existing.broker_order_id = (
                reference.order_id
            )

        existing.submitted_at = (
            result.submitted_at
        )

        existing.updated_at = max(
            existing.updated_at,
            result.submitted_at,
        )

        # ----------------------------------------------------
        # Initial broker acknowledgement only.
        # ----------------------------------------------------

        if broker_snapshot is None:
            self._order_repository.update(
                existing
            )
            return

        assert lifecycle_snapshot is not None

        # ----------------------------------------------------
        # Proven full-fill checkpoint.
        #
        # M06 must have already established FILLED before any
        # authoritative fill facts are written here.
        # ----------------------------------------------------

        if (
            lifecycle_snapshot.intent_id
            != intent.intent_id
        ):
            raise TradingStatePersistenceError(
                "order lifecycle snapshot does not "
                "belong to supplied intent"
            )

        if (
            lifecycle_snapshot.current_state
            is not OrderLifecycleState.FILLED
        ):
            raise TradingStatePersistenceError(
                "authoritative fill persistence requires "
                "M06 FILLED lifecycle"
            )

        if (
            broker_snapshot.status
            is not BrokerOrderStatus.FILLED
        ):
            raise TradingStatePersistenceError(
                "authoritative fill persistence requires "
                "FILLED broker snapshot"
            )

        if reference is None:
            raise TradingStatePersistenceError(
                "authoritative fill persistence requires "
                "broker reference"
            )

        if (
            broker_snapshot.broker_reference
            != reference
        ):
            raise TradingStatePersistenceError(
                "broker fill snapshot identity conflicts "
                "with execution result"
            )

        if (
            broker_snapshot.quantity
            != intent.quantity
        ):
            raise TradingStatePersistenceError(
                "broker fill quantity does not match "
                "order intent"
            )

        if (
            broker_snapshot.filled_quantity
            != intent.quantity
        ):
            raise TradingStatePersistenceError(
                "FILLED broker snapshot must prove "
                "full entry quantity"
            )

        if (
            broker_snapshot.average_price
            is None
        ):
            raise TradingStatePersistenceError(
                "FILLED broker snapshot requires "
                "average fill price"
            )

        durable_order_already_filled = (
            existing.status
            == OrderLifecycleState.FILLED.value
        )

        if (
            durable_order_already_filled
            and existing.position_id is None
        ):
            raise TradingStatePersistenceError(
                "durable FILLED order requires "
                "PositionRecord linkage"
            )

        if (
            existing.filled_quantity
            not in (
                0,
                broker_snapshot.filled_quantity,
            )
        ):
            raise TradingStatePersistenceError(
                "authoritative filled quantity conflicts "
                "with durable order"
            )

        if (
            existing.average_fill_price
            is not None
            and existing.average_fill_price
            != broker_snapshot.average_price
        ):
            raise TradingStatePersistenceError(
                "authoritative average fill price conflicts "
                "with durable order"
            )

        existing.filled_quantity = (
            broker_snapshot.filled_quantity
        )

        existing.average_fill_price = (
            broker_snapshot.average_price
        )

        existing.updated_at = max(
            existing.updated_at,
            broker_snapshot.updated_at,
            lifecycle_snapshot.updated_at,
        )

        # IMPORTANT:
        #
        # existing.status intentionally remains unresolved here.
        #
        # PositionRecord must become durable before a later step
        # is permitted to persist OrderRecord.status == FILLED.

        self._order_repository.update(
            existing
        )

        # ----------------------------------------------------
        # Optional M07 managed-position durability phase.
        #
        # The order_repository update above intentionally occurs
        # first. Its repository owns a separate transaction, so
        # authoritative broker fill facts become durable before
        # PositionRecord persistence is attempted.
        #
        # Durable OrderRecord status remains non-terminal here.
        # ----------------------------------------------------

        if managed_position is None:
            return

        if self._position_repository is None:
            raise TradingStatePersistenceError(
                "managed position persistence requires "
                "position repository"
            )

        position = managed_position.position
        stop_loss = managed_position.stop_loss
        target = managed_position.target

        if (
            position.entry_intent_id
            != intent.intent_id
        ):
            raise TradingStatePersistenceError(
                "managed position does not belong "
                "to supplied order intent"
            )

        if (
            position.signal_id
            != intent.signal.signal_id
        ):
            raise TradingStatePersistenceError(
                "managed position signal conflicts "
                "with order intent"
            )

        if (
            position.selected_option
            != intent.selected_option
        ):
            raise TradingStatePersistenceError(
                "managed position option conflicts "
                "with order intent"
            )

        if (
            position.level
            != intent.signal.level
        ):
            raise TradingStatePersistenceError(
                "managed position level conflicts "
                "with order intent"
            )

        if (
            position.entry_broker_reference
            != broker_snapshot.broker_reference
        ):
            raise TradingStatePersistenceError(
                "managed position broker reference "
                "conflicts with authoritative fill"
            )

        if (
            position.quantity
            != broker_snapshot.filled_quantity
        ):
            raise TradingStatePersistenceError(
                "managed position quantity conflicts "
                "with authoritative fill"
            )

        if (
            position.entry_price
            != broker_snapshot.average_price
        ):
            raise TradingStatePersistenceError(
                "managed position entry price conflicts "
                "with authoritative fill"
            )

        if (
            managed_position.state.value
            != "OPEN"
        ):
            raise TradingStatePersistenceError(
                "initial durable managed position "
                "must be OPEN"
            )

        if (
            managed_position.open_quantity
            != position.quantity
            or managed_position.closed_quantity
            != 0
        ):
            raise TradingStatePersistenceError(
                "initial durable managed position "
                "must retain full open quantity"
            )

        if stop_loss is None:
            raise TradingStatePersistenceError(
                "initial durable managed position "
                "requires stop loss"
            )

        if target is None:
            raise TradingStatePersistenceError(
                "initial durable managed position "
                "requires mapped target"
            )

        position_record = PositionRecord(
            position_id=(
                position.position_id.value
            ),
            risk_id=(
                managed_position.risk_id.value
            ),
            runtime_id=self._runtime_id,
            signal_id=(
                position.signal_id.value
            ),
            entry_order_intent_id=(
                position.entry_intent_id.value
            ),
            security_id=(
                position.security_id
            ),
            symbol=position.symbol,
            option_type=(
                position.option_type.value
            ),
            level=(
                position.level.value
            ),
            original_quantity=(
                managed_position
                .original_quantity
            ),
            open_quantity=(
                managed_position
                .open_quantity
            ),
            closed_quantity=(
                managed_position
                .closed_quantity
            ),
            entry_price=(
                managed_position.entry_price
            ),
            realized_pnl=(
                managed_position.realized_pnl
            ),
            state=(
                managed_position.state.value
            ),
            stop_price=(
                stop_loss.stop_price
            ),
            stop_risk_points=(
                stop_loss.risk_points
            ),
            stop_state=(
                stop_loss.state.value
            ),
            executable_target_price=(
                target.executable_price
            ),
            mapped_target_price=(
                target.mapped_target_price
            ),
            booking_zone_start=(
                target.booking_zone_start
            ),
            booking_zone_end=(
                target.booking_zone_end
            ),
            target_state=(
                target.state.value
            ),
            opened_at=(
                position.filled_at
            ),
            updated_at=(
                managed_position.updated_at
            ),
            closed_at=None,
        )

        durable_position = (
            self._position_repository.get(
                position_record.position_id
            )
        )

        if durable_position is None:
            self._position_repository.add(
                position_record
            )

            durable_position = (
                self._position_repository.get(
                    position_record.position_id
                )
            )

            if durable_position is None:
                raise TradingStatePersistenceError(
                    "position repository did not "
                    "durably return persisted position"
                )

        self._require_matching_fields(
            entity="position",
            identity=(
                position_record.position_id
            ),
            existing=durable_position,
            expected=position_record,
            fields=(
                "risk_id",
                "runtime_id",
                "signal_id",
                "entry_order_intent_id",
                "security_id",
                "symbol",
                "option_type",
                "level",
                "original_quantity",
                "open_quantity",
                "closed_quantity",
                "entry_price",
                "realized_pnl",
                "state",
                "stop_price",
                "stop_risk_points",
                "stop_state",
                "executable_target_price",
                "mapped_target_price",
                "booking_zone_start",
                "booking_zone_end",
                "target_state",
                "opened_at",
                "updated_at",
                "closed_at",
            ),
        )

        # ----------------------------------------------------
        # PositionRecord is now independently durable.
        #
        # Unless explicitly requested, stop here and keep the
        # durable OrderRecord recovery-visible.
        # ----------------------------------------------------

        if not terminalize_order:
            return

        # ----------------------------------------------------
        # Final durable entry-order boundary.
        #
        # Required ordering:
        #
        #   broker fill facts durable
        #       ->
        #   PositionRecord durable
        #       ->
        #   OrderRecord.position_id linked
        #       ->
        #   OrderRecord.status == FILLED
        #
        # P&L and M04 are application-runtime responsibilities
        # and deliberately do not occur here.
        # ----------------------------------------------------

        durable_position = (
            self._position_repository.get(
                position_record.position_id
            )
        )

        if durable_position is None:
            raise TradingStatePersistenceError(
                "durable order FILLED requires "
                "existing durable PositionRecord"
            )

        self._require_matching_fields(
            entity="position",
            identity=(
                position_record.position_id
            ),
            existing=durable_position,
            expected=position_record,
            fields=(
                "risk_id",
                "runtime_id",
                "signal_id",
                "entry_order_intent_id",
                "security_id",
                "symbol",
                "option_type",
                "level",
                "original_quantity",
                "open_quantity",
                "closed_quantity",
                "entry_price",
                "realized_pnl",
                "state",
                "stop_price",
                "stop_risk_points",
                "stop_state",
                "executable_target_price",
                "mapped_target_price",
                "booking_zone_start",
                "booking_zone_end",
                "target_state",
                "opened_at",
                "updated_at",
                "closed_at",
            ),
        )

        if existing.status not in {
            OrderLifecycleState.SUBMITTED.value,
            OrderLifecycleState.FILLED.value,
        }:
            raise TradingStatePersistenceError(
                "durable entry order must be "
                "SUBMITTED or replayed FILLED"
            )

        if (
            existing.status
            == OrderLifecycleState.FILLED.value
            and existing.position_id
            != position_record.position_id
        ):
            raise TradingStatePersistenceError(
                "replayed durable FILLED order position "
                "conflicts with PositionRecord"
            )

        if (
            existing.position_id is not None
            and existing.position_id
            != position_record.position_id
        ):
            raise TradingStatePersistenceError(
                "durable order position identity conflicts "
                "with durable PositionRecord"
            )

        if (
            existing.filled_quantity
            != position_record.original_quantity
        ):
            raise TradingStatePersistenceError(
                "durable order filled quantity conflicts "
                "with durable PositionRecord"
            )

        if (
            existing.average_fill_price
            != position_record.entry_price
        ):
            raise TradingStatePersistenceError(
                "durable order average fill price conflicts "
                "with durable PositionRecord"
            )

        existing.position_id = (
            position_record.position_id
        )

        existing.status = (
            OrderLifecycleState.FILLED.value
        )

        existing.updated_at = max(
            existing.updated_at,
            lifecycle_snapshot.updated_at,
            broker_snapshot.updated_at,
            managed_position.updated_at,
        )

        # Independent OrderRepository transaction.
        self._order_repository.update(
            existing
        )

        durable_order = (
            self._order_repository.get(
                intent.intent_id.value
            )
        )

        if durable_order is None:
            raise TradingStatePersistenceError(
                "terminal durable order could not "
                "be reloaded after persistence"
            )

        if (
            durable_order.status
            != OrderLifecycleState.FILLED.value
        ):
            raise TradingStatePersistenceError(
                "terminal durable order did not persist "
                "FILLED lifecycle"
            )

        if (
            durable_order.position_id
            != position_record.position_id
        ):
            raise TradingStatePersistenceError(
                "terminal durable order did not persist "
                "PositionRecord linkage"
            )

        if (
            durable_order.filled_quantity
            != position_record.original_quantity
        ):
            raise TradingStatePersistenceError(
                "terminal durable order lost "
                "authoritative fill quantity"
            )

        if (
            durable_order.average_fill_price
            != position_record.entry_price
        ):
            raise TradingStatePersistenceError(
                "terminal durable order lost "
                "authoritative average fill price"
            )

    def persist_cancelled_entry_order(
        self,
        *,
        intent: OrderIntent,
        result: ExecutionResult,
        broker_snapshot: BrokerOrderSnapshot,
        lifecycle_snapshot: OrderStateSnapshot,
    ) -> None:
        """
        Persist a proven terminal zero-fill BUY cancellation.

        This checkpoint is allowed only after M06 and the broker
        independently agree that the entry is CANCELLED with
        zero filled quantity.

        Unlike a FILLED entry, no PositionRecord is required
        because zero market exposure exists.
        """

        if not isinstance(
            intent,
            OrderIntent,
        ):
            raise TypeError(
                "intent must be OrderIntent"
            )

        if not isinstance(
            result,
            ExecutionResult,
        ):
            raise TypeError(
                "result must be ExecutionResult"
            )

        if not isinstance(
            broker_snapshot,
            BrokerOrderSnapshot,
        ):
            raise TypeError(
                "broker_snapshot must be BrokerOrderSnapshot"
            )

        if not isinstance(
            lifecycle_snapshot,
            OrderStateSnapshot,
        ):
            raise TypeError(
                "lifecycle_snapshot must be OrderStateSnapshot"
            )

        if result.intent_id != intent.intent_id:
            raise TradingStatePersistenceError(
                "execution result does not belong "
                "to cancelled entry intent"
            )

        if (
            lifecycle_snapshot.intent_id
            != intent.intent_id
        ):
            raise TradingStatePersistenceError(
                "order lifecycle snapshot does not belong "
                "to cancelled entry intent"
            )

        if (
            lifecycle_snapshot.current_state
            is not OrderLifecycleState.CANCELLED
        ):
            raise TradingStatePersistenceError(
                "cancelled entry persistence requires "
                "M06 CANCELLED lifecycle"
            )

        if (
            broker_snapshot.status
            is not BrokerOrderStatus.CANCELLED
        ):
            raise TradingStatePersistenceError(
                "cancelled entry persistence requires "
                "CANCELLED broker snapshot"
            )

        if broker_snapshot.filled_quantity != 0:
            raise TradingStatePersistenceError(
                "cancelled entry persistence requires "
                "zero filled quantity"
            )

        if (
            broker_snapshot.quantity
            != intent.quantity
        ):
            raise TradingStatePersistenceError(
                "cancelled broker quantity does not match "
                "entry intent"
            )

        reference = result.broker_reference

        if reference is None:
            raise TradingStatePersistenceError(
                "cancelled entry persistence requires "
                "broker reference"
            )

        if (
            broker_snapshot.broker_reference
            != reference
        ):
            raise TradingStatePersistenceError(
                "cancelled broker snapshot identity conflicts "
                "with entry execution result"
            )

        existing = (
            self._order_repository.get(
                intent.intent_id.value
            )
        )

        if existing is None:
            raise TradingStatePersistenceError(
                "cancelled entry cannot be persisted "
                "before durable order exists"
            )

        if existing.side != "BUY":
            raise TradingStatePersistenceError(
                "cancelled entry persistence requires BUY order"
            )

        if existing.quantity != intent.quantity:
            raise TradingStatePersistenceError(
                "durable cancelled order quantity conflicts "
                "with entry intent"
            )

        if existing.filled_quantity != 0:
            raise TradingStatePersistenceError(
                "durable cancelled entry already records fill"
            )

        if (
            existing.broker_name
            and existing.broker_name
            != reference.broker_name
        ):
            raise TradingStatePersistenceError(
                "cancelled entry broker identity conflicts "
                "with durable order"
            )

        if (
            existing.broker_order_id
            and existing.broker_order_id
            != reference.order_id
        ):
            raise TradingStatePersistenceError(
                "cancelled broker order identity conflicts "
                "with durable order"
            )

        if (
            existing.status
            == OrderLifecycleState.FILLED.value
        ):
            raise TradingStatePersistenceError(
                "FILLED durable entry cannot become CANCELLED"
            )

        existing.broker_name = (
            reference.broker_name
        )

        existing.broker_order_id = (
            reference.order_id
        )

        existing.status = (
            OrderLifecycleState
            .CANCELLED
            .value
        )

        existing.filled_quantity = 0
        existing.average_fill_price = None

        existing.updated_at = max(
            existing.updated_at,
            broker_snapshot.updated_at,
            lifecycle_snapshot.updated_at,
        )

        self._order_repository.update(
            existing
        )


    def _add_or_validate_signal(
        self,
        expected: SignalRecord,
    ) -> None:
        existing = (
            self._signal_repository.get(
                expected.signal_id
            )
        )

        if existing is None:
            self._signal_repository.add(
                expected
            )
            return

        self._require_matching_fields(
            entity="signal",
            identity=expected.signal_id,
            existing=existing,
            expected=expected,
            fields=(
                "runtime_id",
                "trading_date",
                "level",
                "signal_type",
                "option_type",
                "underlying_price",
                "quantity",
                "status",
                "reason",
                "created_at",
            ),
        )

    def _add_or_validate_selection(
        self,
        expected:
            OptionSelectionRecord,
    ) -> None:
        existing = (
            self
            ._option_selection_repository
            .get(
                expected.selection_id
            )
        )

        if existing is None:
            (
                self
                ._option_selection_repository
                .add(
                    expected
                )
            )
            return

        self._require_matching_fields(
            entity="option selection",
            identity=(
                expected.selection_id
            ),
            existing=existing,
            expected=expected,
            fields=(
                "runtime_id",
                "signal_id",
                "underlying_symbol",
                "symbol",
                "security_id",
                "option_type",
                "strike",
                "expiry",
                "lot_size",
                "ltp",
                "delta",
                "target_delta",
                "bid",
                "ask",
                "volume",
                "open_interest",
                "quote_received_at",
                "selected_at",
            ),
        )

    @staticmethod
    def _require_matching_fields(
        *,
        entity: str,
        identity: str,
        existing: Any,
        expected: Any,
        fields: tuple[str, ...],
    ) -> None:
        for field in fields:
            if (
                getattr(
                    existing,
                    field,
                )
                != getattr(
                    expected,
                    field,
                )
            ):
                raise TradingStatePersistenceError(
                    f"existing durable {entity} "
                    f"conflicts for {identity}: "
                    f"{field}"
                )


class DurableEntryBrokerExecutionProvider(
    BrokerExecutionProvider
):
    """
    BrokerExecutionProvider decorator that establishes durable
    SUBMITTED state before delegating to the real provider.

    This class does not decide whether an order is eligible.
    M06 remains authoritative for order lifecycle and
    idempotency.

    It only enforces:

        no durable SUBMITTED state
            ->
        no broker call
    """

    def __init__(
        self,
        *,
        delegate:
            BrokerExecutionProvider,
        persistence:
            SQLAlchemyEntryPersistenceService,
        state_machine:
            OrderStateMachine,
    ) -> None:
        if not isinstance(
            delegate,
            BrokerExecutionProvider,
        ):
            raise TypeError(
                "delegate must implement "
                "BrokerExecutionProvider"
            )

        if not isinstance(
            persistence,
            SQLAlchemyEntryPersistenceService,
        ):
            raise TypeError(
                "persistence must be "
                "SQLAlchemyEntryPersistenceService"
            )

        if not isinstance(
            state_machine,
            OrderStateMachine,
        ):
            raise TypeError(
                "state_machine must be "
                "OrderStateMachine"
            )

        self._delegate = delegate
        self._persistence = (
            persistence
        )
        self._state_machine = (
            state_machine
        )

    @property
    def broker_name(
        self,
    ) -> str:
        return self._delegate.broker_name

    @property
    def delegate(
        self,
    ) -> BrokerExecutionProvider:
        return self._delegate

    @property
    def persistence(
        self,
    ) -> SQLAlchemyEntryPersistenceService:
        return self._persistence

    def submit_order(
        self,
        intent: OrderIntent,
    ) -> ExecutionResult:
        lifecycle_snapshot = (
            self._state_machine.snapshot(
                intent.intent_id
            )
        )

        self._persistence.persist_pre_broker_submission(
            intent=intent,
            broker_name=(
                self._delegate.broker_name
            ),
            lifecycle_snapshot=(
                lifecycle_snapshot
            ),
        )

        # ----------------------------------------------------
        # REAL BROKER BOUNDARY
        #
        # Nothing above this line may be skipped.
        # If persistence failed, execution never reaches here.
        # ----------------------------------------------------
        result = (
            self._delegate.submit_order(
                intent
            )
        )

        # Capture broker acknowledgement/order identity before
        # returning control to M06.
        self._persistence.persist_broker_execution_result(
            intent=intent,
            result=result,
        )

        return result

    def cancel_order(
        self,
        broker_reference,
    ) -> BrokerCancellationResult:
        return self._delegate.cancel_order(
            broker_reference
        )

    def get_order_status(
        self,
        broker_reference,
    ) -> BrokerOrderSnapshot:
        return self._delegate.get_order_status(
            broker_reference
        )


__all__ = [
    "DurableEntryBrokerExecutionProvider",
    "SQLAlchemyEntryPersistenceService",
    "TradingStatePersistenceError",
]
