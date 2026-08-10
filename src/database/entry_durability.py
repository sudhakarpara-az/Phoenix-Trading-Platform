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
    SignalRecord,
)
from src.execution.broker_execution_provider import (
    BrokerCancellationResult,
    BrokerExecutionProvider,
    BrokerOrderSnapshot,
)
from src.execution.execution_types import (
    ExecutionResult,
    OrderIntent,
)
from src.execution.order_state_machine import (
    OrderLifecycleState,
    OrderStateMachine,
    OrderStateSnapshot,
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
    ) -> None:
        """
        Persist broker acknowledgement immediately after the
        provider returns.

        M06 still owns lifecycle-state mapping. Therefore this
        method deliberately preserves the existing persisted
        lifecycle status and only records broker acknowledgement
        metadata available at this point.

        A later application persistence step will checkpoint the
        authoritative post-M06 lifecycle state.
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

            existing.broker_name = (
                reference.broker_name
            )

            existing.broker_order_id = (
                reference.order_id
            )

        existing.submitted_at = (
            result.submitted_at
        )

        existing.updated_at = (
            result.submitted_at
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