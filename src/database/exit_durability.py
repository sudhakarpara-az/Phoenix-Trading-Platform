"""
Phoenix durable SELL / exit execution boundary.

Crash-safe SELL ordering:

    ExitOrderIntent
        ->
    durable OrderRecord(SUBMITTED, SELL)
        ->
    broker SELL submission
        ->
    broker acknowledgement
        ->
    durable OrderFillRecord(s)
        ->
    M07 applies only unapplied SELL fill quantity
        ->
    durable PositionRecord update
        ->
    terminal SELL OrderRecord

A terminal broker snapshot must never make the durable SELL
terminal before the matching PositionRecord reflects that fill.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import (
    isclose,
    isfinite,
)

from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyOrderFillRepository,
    SQLAlchemyOrderRepository,
    SQLAlchemyPositionRepository,
)
from src.database.schema import (
    OrderFillRecord,
    OrderRecord,
    PositionRecord,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
)
from src.execution.exit_execution_provider import (
    ExitCancellationResult,
    ExitExecutionProvider,
    ExitExecutionResult,
    ExitOrderIntent,
    ExitOrderSnapshot,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
)


class ExitStatePersistenceError(
    RuntimeError
):
    """
    Durable SELL persistence contract violation.
    """


@dataclass(
    frozen=True,
    slots=True,
)
class ExitFillDelta:
    """
    Broker-confirmed SELL fill not yet reflected in the durable
    PositionRecord.

    quantity == 0 means the durable position already reflects
    every persisted fill for this SELL order.
    """

    quantity: int

    price: float | None

    filled_at: datetime

    def __post_init__(
        self,
    ) -> None:
        if self.quantity < 0:
            raise ValueError(
                "exit fill delta quantity cannot be negative"
            )

        if self.quantity == 0:
            if self.price is not None:
                raise ValueError(
                    "zero exit fill delta cannot have price"
                )

            return

        if self.price is None:
            raise ValueError(
                "positive exit fill delta requires price"
            )

        if (
            not isfinite(
                self.price
            )
            or self.price <= 0
        ):
            raise ValueError(
                "exit fill delta price must be "
                "positive and finite"
            )

    @property
    def has_fill(
        self,
    ) -> bool:
        return self.quantity > 0


class SQLAlchemyExitPersistenceService:
    """
    Durable SELL state owner.

    Existing broker-submission behavior remains backward
    compatible.

    Optional fill/position repositories activate the next
    crash-safe boundary:

        broker cumulative fill
            ->
        OrderFillRecord
            ->
        M07 ManagedPosition
            ->
        PositionRecord
            ->
        terminal OrderRecord
    """

    _TERMINAL_BROKER_STATUSES = frozenset(
        {
            BrokerOrderStatus.FILLED,
            BrokerOrderStatus.CANCELLED,
            BrokerOrderStatus.REJECTED,
        }
    )

    _TERMINAL_DURABLE_STATUSES = frozenset(
        {
            "FILLED",
            "CANCELLED",
            "REJECTED",
            "FAILED",
        }
    )

    def __init__(
        self,
        *,
        runtime_id: str,
        order_repository:
            SQLAlchemyOrderRepository,
        fill_repository:
            SQLAlchemyOrderFillRepository
            | None = None,
        position_repository:
            SQLAlchemyPositionRepository
            | None = None,
    ) -> None:
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

        self._order_repository = (
            order_repository
        )

        self._fill_repository = (
            fill_repository
        )

        self._position_repository = (
            position_repository
        )

    @property
    def runtime_id(
        self,
    ) -> str:
        return self._runtime_id

    @property
    def order_repository(
        self,
    ) -> SQLAlchemyOrderRepository:
        return self._order_repository

    @property
    def fill_repository(
        self,
    ) -> (
        SQLAlchemyOrderFillRepository
        | None
    ):
        return self._fill_repository

    @property
    def position_repository(
        self,
    ) -> (
        SQLAlchemyPositionRepository
        | None
    ):
        return self._position_repository

    # ========================================================
    # Pre-broker SELL durability
    # ========================================================

    def persist_pre_broker_submission(
        self,
        *,
        intent: ExitOrderIntent,
        broker_name: str,
    ) -> None:
        """
        Persist SELL intent before any broker API call.

        An existing durable intent blocks replay.
        """

        if not isinstance(
            intent,
            ExitOrderIntent,
        ):
            raise TypeError(
                "intent must be ExitOrderIntent"
            )

        normalized_broker_name = (
            broker_name.strip()
        )

        if not normalized_broker_name:
            raise ValueError(
                "broker_name cannot be empty"
            )

        existing = (
            self._order_repository.get(
                intent.intent_id.value
            )
        )

        if existing is not None:
            raise ExitStatePersistenceError(
                "durable SELL order already exists "
                f"for intent "
                f"{intent.intent_id.value}"
            )

        record = OrderRecord(
            order_intent_id=(
                intent.intent_id.value
            ),
            runtime_id=self._runtime_id,
            signal_id=None,
            position_id=(
                intent.position_id.value
            ),
            security_id=(
                intent.security_id
            ),
            symbol=intent.symbol,
            side="SELL",
            order_type=(
                intent.order_type.value
            ),
            reason=(
                intent.reason.value
            ),
            quantity=intent.quantity,
            limit_price=intent.price,
            execution_mode="LIVE",
            status="SUBMITTED",
            broker_name=(
                normalized_broker_name
            ),
            broker_order_id=None,
            filled_quantity=0,
            average_fill_price=None,
            created_at=intent.created_at,
            submitted_at=None,
            updated_at=intent.created_at,
        )

        self._order_repository.add(
            record
        )

    # ========================================================
    # Broker submission acknowledgement
    # ========================================================

    def persist_broker_submission_result(
        self,
        *,
        intent: ExitOrderIntent,
        result: ExitExecutionResult,
    ) -> None:
        """
        Persist broker acknowledgement after SELL submission.

        Successful broker acknowledgement intentionally remains
        recovery-visible.

        FILLED is not terminalized here because M07 position
        durability has not yet occurred.
        """

        if not isinstance(
            intent,
            ExitOrderIntent,
        ):
            raise TypeError(
                "intent must be ExitOrderIntent"
            )

        if not isinstance(
            result,
            ExitExecutionResult,
        ):
            raise TypeError(
                "result must be ExitExecutionResult"
            )

        if (
            result.intent_id
            != intent.intent_id
        ):
            raise ExitStatePersistenceError(
                "exit execution result does not belong "
                "to supplied SELL intent"
            )

        existing = self._require_sell_order(
            intent
        )

        reference = (
            result.broker_reference
        )

        if reference is not None:
            self._apply_broker_reference(
                existing=existing,
                reference=reference,
            )

        existing.submitted_at = (
            result.submitted_at
        )

        existing.updated_at = max(
            existing.updated_at,
            result.submitted_at,
        )

        if result.success:
            existing.status = (
                "SUBMITTED"
            )

        elif result.status in {
            BrokerOrderStatus.REJECTED,
            BrokerOrderStatus.CANCELLED,
        }:
            existing.status = (
                result.status.value
            )

        else:
            # UNKNOWN may mean the broker accepted the SELL.
            # Never infer "not submitted".
            existing.status = (
                "SUBMITTED"
            )

        self._order_repository.update(
            existing
        )

    # ========================================================
    # Broker snapshot -> fill ledger
    # ========================================================

    def checkpoint_broker_snapshot(
        self,
        *,
        intent: ExitOrderIntent,
        snapshot: ExitOrderSnapshot,
    ) -> ExitFillDelta:
        """
        Persist authoritative broker SELL fill facts.

        Ordering inside this method:

            broker cumulative snapshot
                ->
            append new OrderFillRecord first
                ->
            update recovery-visible OrderRecord facts
                ->
            calculate quantity still missing from PositionRecord

        A terminal broker state is deliberately NOT allowed to
        terminalize the durable SELL here.

        That occurs only after
        persist_managed_position_after_snapshot().
        """

        if not isinstance(
            intent,
            ExitOrderIntent,
        ):
            raise TypeError(
                "intent must be ExitOrderIntent"
            )

        if not isinstance(
            snapshot,
            ExitOrderSnapshot,
        ):
            raise TypeError(
                "snapshot must be ExitOrderSnapshot"
            )

        (
            fill_repository,
            position_repository,
        ) = self._require_fill_boundary()

        existing = self._require_sell_order(
            intent
        )

        self._validate_snapshot_identity(
            intent=intent,
            existing=existing,
            snapshot=snapshot,
        )

        fills = self._ordered_fills(
            fill_repository.list_by_order(
                intent.intent_id.value
            )
        )

        durable_fill_quantity = sum(
            fill.quantity
            for fill in fills
        )

        durable_fill_notional = sum(
            fill.quantity
            * fill.price
            for fill in fills
        )

        if (
            durable_fill_quantity
            > intent.quantity
        ):
            raise ExitStatePersistenceError(
                "durable SELL fills exceed "
                "SELL intent quantity"
            )

        if (
            snapshot.filled_quantity
            < durable_fill_quantity
        ):
            raise ExitStatePersistenceError(
                "broker SELL filled quantity regressed "
                "below durable fill ledger"
            )

        if snapshot.filled_quantity > 0:
            if snapshot.average_price is None:
                raise ExitStatePersistenceError(
                    "broker SELL fill requires "
                    "average price"
                )

            if (
                not isfinite(
                    snapshot.average_price
                )
                or snapshot.average_price <= 0
            ):
                raise ExitStatePersistenceError(
                    "broker SELL average price must be "
                    "positive and finite"
                )

        # ----------------------------------------------------
        # Append only the new cumulative broker fill delta.
        #
        # Dhan may expose a cumulative average price rather than
        # individual execution prices. Recover the incremental
        # execution price from cumulative notional.
        # ----------------------------------------------------

        if (
            snapshot.filled_quantity
            > durable_fill_quantity
        ):
            assert (
                snapshot.average_price
                is not None
            )

            new_quantity = (
                snapshot.filled_quantity
                - durable_fill_quantity
            )

            new_total_notional = (
                snapshot.average_price
                * snapshot.filled_quantity
            )

            new_notional = (
                new_total_notional
                - durable_fill_notional
            )

            new_price = (
                new_notional
                / new_quantity
            )

            if (
                not isfinite(
                    new_price
                )
                or new_price <= 0
            ):
                raise ExitStatePersistenceError(
                    "derived incremental SELL fill price "
                    "is invalid"
                )

            fill_record = OrderFillRecord(
                fill_id=(
                    "EXIT-FILL:"
                    f"{intent.intent_id.value}:"
                    f"{snapshot.filled_quantity:010d}"
                ),
                order_intent_id=(
                    intent.intent_id.value
                ),
                broker_trade_id=None,
                quantity=new_quantity,
                price=new_price,
                filled_at=(
                    snapshot.updated_at
                ),
            )

            fill_repository.add(
                fill_record
            )

            fills = self._ordered_fills(
                fill_repository.list_by_order(
                    intent.intent_id.value
                )
            )

            durable_fill_quantity = sum(
                fill.quantity
                for fill in fills
            )

            durable_fill_notional = sum(
                fill.quantity
                * fill.price
                for fill in fills
            )

        # ----------------------------------------------------
        # Same cumulative quantity replay.
        #
        # Broker cumulative average must still agree with the
        # already-durable fill ledger.
        # ----------------------------------------------------

        if durable_fill_quantity > 0:
            if snapshot.average_price is None:
                raise ExitStatePersistenceError(
                    "durable SELL fill replay requires "
                    "broker average price"
                )

            ledger_average = (
                durable_fill_notional
                / durable_fill_quantity
            )

            if not isclose(
                ledger_average,
                snapshot.average_price,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ExitStatePersistenceError(
                    "broker SELL cumulative average "
                    "conflicts with durable fill ledger"
                )

        if (
            durable_fill_quantity
            != snapshot.filled_quantity
        ):
            raise ExitStatePersistenceError(
                "durable SELL fill ledger does not "
                "match broker cumulative fill quantity"
            )

        # ----------------------------------------------------
        # Persist broker snapshot facts.
        #
        # Terminal status is intentionally withheld until the
        # matching PositionRecord transaction succeeds.
        # ----------------------------------------------------

        existing = self._require_sell_order(
            intent
        )

        self._apply_broker_reference(
            existing=existing,
            reference=(
                snapshot.broker_reference
            ),
        )

        existing.filled_quantity = (
            snapshot.filled_quantity
        )

        existing.average_fill_price = (
            snapshot.average_price
        )

        existing.updated_at = max(
            existing.updated_at,
            snapshot.updated_at,
        )

        if (
            snapshot.status
            in self._TERMINAL_BROKER_STATUSES
        ):
            # If already terminal from an earlier completed
            # replay, preserve it. Otherwise remain unresolved.
            if (
                existing.status
                in self._TERMINAL_DURABLE_STATUSES
            ):
                if (
                    existing.status
                    != snapshot.status.value
                ):
                    raise ExitStatePersistenceError(
                        "terminal durable SELL status "
                        "conflicts with broker snapshot"
                    )

            # Otherwise preserve current non-terminal state.

        elif (
            snapshot.status
            is BrokerOrderStatus.UNKNOWN
        ):
            existing.status = (
                "SUBMITTED"
            )

        else:
            existing.status = (
                snapshot.status.value
            )

        self._order_repository.update(
            existing
        )

        # ----------------------------------------------------
        # Determine which durable fill quantity M07 still needs
        # to apply.
        #
        # IMPORTANT:
        #
        # Do NOT compare only with OrderRecord.filled_quantity.
        #
        # A crash may occur after the fill ledger/order snapshot
        # is durable but before PositionRecord is updated.
        # ----------------------------------------------------

        durable_position = (
            position_repository.get(
                intent.position_id.value
            )
        )

        if durable_position is None:
            raise ExitStatePersistenceError(
                "SELL fill durability requires "
                "existing PositionRecord"
            )

        baseline_closed_quantity = (
            durable_position.original_quantity
            - intent.quantity
        )

        if baseline_closed_quantity < 0:
            raise ExitStatePersistenceError(
                "SELL intent quantity exceeds original "
                "position quantity"
            )

        applied_quantity = (
            durable_position.closed_quantity
            - baseline_closed_quantity
        )

        if applied_quantity < 0:
            raise ExitStatePersistenceError(
                "durable PositionRecord closed quantity "
                "precedes SELL baseline"
            )

        if (
            applied_quantity
            > durable_fill_quantity
        ):
            raise ExitStatePersistenceError(
                "durable PositionRecord reflects more "
                "SELL quantity than fill ledger"
            )

        pending_quantity = (
            durable_fill_quantity
            - applied_quantity
        )

        if pending_quantity == 0:
            return ExitFillDelta(
                quantity=0,
                price=None,
                filled_at=(
                    snapshot.updated_at
                ),
            )

        pending_notional = (
            self._pending_notional(
                fills=fills,
                already_applied=(
                    applied_quantity
                ),
            )
        )

        pending_price = (
            pending_notional
            / pending_quantity
        )

        return ExitFillDelta(
            quantity=pending_quantity,
            price=pending_price,
            filled_at=(
                snapshot.updated_at
            ),
        )

    # ========================================================
    # M07 ManagedPosition -> PositionRecord -> terminal SELL
    # ========================================================

    def persist_managed_position_after_snapshot(
        self,
        *,
        intent: ExitOrderIntent,
        snapshot: ExitOrderSnapshot,
        managed_position: ManagedPosition,
    ) -> None:
        """
        Persist M07 position state after applying the broker SELL
        fill delta.

        Only after PositionRecord is durably updated may a
        terminal broker snapshot terminalize OrderRecord.
        """

        if not isinstance(
            intent,
            ExitOrderIntent,
        ):
            raise TypeError(
                "intent must be ExitOrderIntent"
            )

        if not isinstance(
            snapshot,
            ExitOrderSnapshot,
        ):
            raise TypeError(
                "snapshot must be ExitOrderSnapshot"
            )

        if not isinstance(
            managed_position,
            ManagedPosition,
        ):
            raise TypeError(
                "managed_position must be ManagedPosition"
            )

        (
            fill_repository,
            position_repository,
        ) = self._require_fill_boundary()

        order = self._require_sell_order(
            intent
        )

        self._validate_snapshot_identity(
            intent=intent,
            existing=order,
            snapshot=snapshot,
        )

        fills = self._ordered_fills(
            fill_repository.list_by_order(
                intent.intent_id.value
            )
        )

        ledger_quantity = sum(
            fill.quantity
            for fill in fills
        )

        if (
            ledger_quantity
            != snapshot.filled_quantity
        ):
            raise ExitStatePersistenceError(
                "PositionRecord cannot advance before "
                "SELL fill ledger matches broker snapshot"
            )

        durable_position = (
            position_repository.get(
                intent.position_id.value
            )
        )

        if durable_position is None:
            raise ExitStatePersistenceError(
                "SELL PositionRecord does not exist"
            )

        self._validate_managed_identity(
            intent=intent,
            durable=durable_position,
            managed=managed_position,
        )

        baseline_closed_quantity = (
            durable_position.original_quantity
            - intent.quantity
        )

        if baseline_closed_quantity < 0:
            raise ExitStatePersistenceError(
                "SELL intent quantity exceeds original "
                "position quantity"
            )

        expected_closed_quantity = (
            baseline_closed_quantity
            + snapshot.filled_quantity
        )

        expected_open_quantity = (
            durable_position.original_quantity
            - expected_closed_quantity
        )

        if (
            expected_closed_quantity < 0
            or expected_open_quantity < 0
        ):
            raise ExitStatePersistenceError(
                "broker SELL snapshot over-closes "
                "durable position"
            )

        if (
            managed_position.closed_quantity
            != expected_closed_quantity
            or managed_position.open_quantity
            != expected_open_quantity
        ):
            raise ExitStatePersistenceError(
                "managed position quantities do not "
                "reflect broker SELL snapshot"
            )

        if (
            snapshot.status
            is BrokerOrderStatus.FILLED
        ):
            if (
                snapshot.filled_quantity
                != intent.quantity
            ):
                raise ExitStatePersistenceError(
                    "FILLED SELL snapshot must equal "
                    "SELL intent quantity"
                )

            if managed_position.open_quantity != 0:
                raise ExitStatePersistenceError(
                    "FILLED Phoenix SELL must leave "
                    "zero open quantity"
                )

            if (
                managed_position.state
                is not ManagedPositionState.CLOSED
            ):
                raise ExitStatePersistenceError(
                    "FILLED SELL requires CLOSED "
                    "managed position"
                )

        stop_loss = (
            managed_position.stop_loss
        )

        target = (
            managed_position.target
        )

        durable_position.open_quantity = (
            managed_position.open_quantity
        )

        durable_position.closed_quantity = (
            managed_position.closed_quantity
        )

        durable_position.realized_pnl = (
            managed_position.realized_pnl
        )

        durable_position.state = (
            managed_position.state.value
        )

        durable_position.stop_price = (
            None
            if stop_loss is None
            else stop_loss.stop_price
        )

        durable_position.stop_risk_points = (
            None
            if stop_loss is None
            else stop_loss.risk_points
        )

        durable_position.stop_state = (
            None
            if stop_loss is None
            else stop_loss.state.value
        )

        durable_position.executable_target_price = (
            None
            if target is None
            else target.executable_price
        )

        durable_position.mapped_target_price = (
            None
            if target is None
            else target.mapped_target_price
        )

        durable_position.booking_zone_start = (
            None
            if target is None
            else target.booking_zone_start
        )

        durable_position.booking_zone_end = (
            None
            if target is None
            else target.booking_zone_end
        )

        durable_position.target_state = (
            None
            if target is None
            else target.state.value
        )

        durable_position.updated_at = (
            managed_position.updated_at
        )

        durable_position.closed_at = (
            managed_position.updated_at
            if (
                managed_position.state
                is ManagedPositionState.CLOSED
            )
            else None
        )

        position_repository.update(
            durable_position
        )

        # ----------------------------------------------------
        # Independent durability proof.
        # ----------------------------------------------------

        persisted_position = (
            position_repository.get(
                intent.position_id.value
            )
        )

        if persisted_position is None:
            raise ExitStatePersistenceError(
                "PositionRecord update was not durable"
            )

        if (
            persisted_position.open_quantity
            != managed_position.open_quantity
            or persisted_position.closed_quantity
            != managed_position.closed_quantity
            or not isclose(
                persisted_position.realized_pnl,
                managed_position.realized_pnl,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            or persisted_position.state
            != managed_position.state.value
        ):
            raise ExitStatePersistenceError(
                "durable PositionRecord does not match "
                "M07 managed position"
            )

        # ----------------------------------------------------
        # PositionRecord is now durable.
        #
        # Only NOW may terminal broker truth terminalize the
        # SELL OrderRecord.
        # ----------------------------------------------------

        if (
            snapshot.status
            not in self._TERMINAL_BROKER_STATUSES
        ):
            return

        order = self._require_sell_order(
            intent
        )

        order.filled_quantity = (
            snapshot.filled_quantity
        )

        order.average_fill_price = (
            snapshot.average_price
        )

        order.status = (
            snapshot.status.value
        )

        order.updated_at = max(
            order.updated_at,
            snapshot.updated_at,
            persisted_position.updated_at,
        )

        self._order_repository.update(
            order
        )

        persisted_order = (
            self._order_repository.get(
                intent.intent_id.value
            )
        )

        if persisted_order is None:
            raise ExitStatePersistenceError(
                "terminal SELL OrderRecord disappeared"
            )

        if (
            persisted_order.status
            != snapshot.status.value
        ):
            raise ExitStatePersistenceError(
                "terminal SELL state was not durable"
            )

    # ========================================================
    # M07 lifecycle-only durability
    # ========================================================

    def persist_managed_position_state(
        self,
        *,
        managed_position: ManagedPosition,
    ) -> None:
        """
        Persist M07 lifecycle state without changing SELL order
        terminality.

        Used for transitions such as:

            OPEN/PARTIALLY_EXITED
                ->
            EXIT_PENDING

            EXIT_PENDING
                ->
            RECONCILIATION_REQUIRED

            EXIT_PENDING / RECONCILIATION_REQUIRED
                ->
            OPEN / PARTIALLY_EXITED

        This method NEVER terminalizes OrderRecord.
        """

        if not isinstance(
            managed_position,
            ManagedPosition,
        ):
            raise TypeError(
                "managed_position must be ManagedPosition"
            )

        position_repository = (
            self._position_repository
        )

        if position_repository is None:
            raise ExitStatePersistenceError(
                "managed position durability requires "
                "position repository"
            )

        position = (
            managed_position.position
        )

        durable = (
            position_repository.get(
                position.position_id.value
            )
        )

        if durable is None:
            raise ExitStatePersistenceError(
                "managed PositionRecord does not exist"
            )

        # ----------------------------------------------------
        # Immutable identity protection
        # ----------------------------------------------------

        if (
            durable.position_id
            != position.position_id.value
            or durable.risk_id
            != managed_position.risk_id.value
            or durable.signal_id
            != position.signal_id.value
            or durable.entry_order_intent_id
            != position.entry_intent_id.value
            or durable.security_id
            != position.security_id
            or durable.symbol
            != position.symbol
            or durable.option_type
            != position.option_type.value
            or durable.level
            != position.level.value
            or durable.original_quantity
            != position.quantity
        ):
            raise ExitStatePersistenceError(
                "managed position identity conflicts "
                "with durable PositionRecord"
            )

        if not isclose(
            durable.entry_price,
            position.entry_price,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ExitStatePersistenceError(
                "managed position entry price conflicts "
                "with durable PositionRecord"
            )

        # ----------------------------------------------------
        # Quantity / P&L protection
        # ----------------------------------------------------

        if (
            managed_position.open_quantity < 0
            or managed_position.closed_quantity < 0
            or (
                managed_position.open_quantity
                + managed_position.closed_quantity
                != durable.original_quantity
            )
        ):
            raise ExitStatePersistenceError(
                "managed position quantities are invalid"
            )

        if (
            managed_position.closed_quantity
            < durable.closed_quantity
            or managed_position.open_quantity
            > durable.open_quantity
        ):
            raise ExitStatePersistenceError(
                "managed position state would regress "
                "durable exit quantities"
            )

        if not isfinite(
            managed_position.realized_pnl
        ):
            raise ExitStatePersistenceError(
                "managed position realized P&L "
                "must be finite"
            )

        stop_loss = (
            managed_position.stop_loss
        )

        target = (
            managed_position.target
        )

        durable.open_quantity = (
            managed_position.open_quantity
        )

        durable.closed_quantity = (
            managed_position.closed_quantity
        )

        durable.realized_pnl = (
            managed_position.realized_pnl
        )

        durable.state = (
            managed_position.state.value
        )

        durable.stop_price = (
            None
            if stop_loss is None
            else stop_loss.stop_price
        )

        durable.stop_risk_points = (
            None
            if stop_loss is None
            else stop_loss.risk_points
        )

        durable.stop_state = (
            None
            if stop_loss is None
            else stop_loss.state.value
        )

        durable.executable_target_price = (
            None
            if target is None
            else target.executable_price
        )

        durable.mapped_target_price = (
            None
            if target is None
            else target.mapped_target_price
        )

        durable.booking_zone_start = (
            None
            if target is None
            else target.booking_zone_start
        )

        durable.booking_zone_end = (
            None
            if target is None
            else target.booking_zone_end
        )

        durable.target_state = (
            None
            if target is None
            else target.state.value
        )

        durable.updated_at = (
            managed_position.updated_at
        )

        durable.closed_at = (
            managed_position.updated_at
            if (
                managed_position.state
                is ManagedPositionState.CLOSED
            )
            else None
        )

        position_repository.update(
            durable
        )

        # ----------------------------------------------------
        # Independent durability proof
        # ----------------------------------------------------

        persisted = (
            position_repository.get(
                position.position_id.value
            )
        )

        if persisted is None:
            raise ExitStatePersistenceError(
                "managed PositionRecord update disappeared"
            )

        if (
            persisted.open_quantity
            != managed_position.open_quantity
            or persisted.closed_quantity
            != managed_position.closed_quantity
            or persisted.state
            != managed_position.state.value
            or not isclose(
                persisted.realized_pnl,
                managed_position.realized_pnl,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        ):
            raise ExitStatePersistenceError(
                "durable PositionRecord does not match "
                "managed lifecycle state"
            )


    # ========================================================
    # Internal validation
    # ========================================================

    def _require_sell_order(
        self,
        intent: ExitOrderIntent,
    ) -> OrderRecord:
        existing = (
            self._order_repository.get(
                intent.intent_id.value
            )
        )

        if existing is None:
            raise ExitStatePersistenceError(
                "durable SELL order does not exist"
            )

        if existing.runtime_id != self._runtime_id:
            raise ExitStatePersistenceError(
                "durable SELL runtime identity mismatch"
            )

        if existing.side != "SELL":
            raise ExitStatePersistenceError(
                "durable order is not a SELL"
            )

        if (
            existing.position_id
            != intent.position_id.value
        ):
            raise ExitStatePersistenceError(
                "durable SELL position identity "
                "does not match intent"
            )

        if (
            existing.security_id
            != intent.security_id
            or existing.symbol
            != intent.symbol
            or existing.quantity
            != intent.quantity
            or existing.order_type
            != intent.order_type.value
        ):
            raise ExitStatePersistenceError(
                "durable SELL order conflicts "
                "with supplied intent"
            )

        return existing

    def _require_fill_boundary(
        self,
    ) -> tuple[
        SQLAlchemyOrderFillRepository,
        SQLAlchemyPositionRepository,
    ]:
        if self._fill_repository is None:
            raise ExitStatePersistenceError(
                "SELL fill durability requires "
                "order fill repository"
            )

        if self._position_repository is None:
            raise ExitStatePersistenceError(
                "SELL fill durability requires "
                "position repository"
            )

        return (
            self._fill_repository,
            self._position_repository,
        )

    @staticmethod
    def _apply_broker_reference(
        *,
        existing: OrderRecord,
        reference: BrokerOrderReference,
    ) -> None:
        if (
            existing.broker_name
            and existing.broker_name
            != reference.broker_name
        ):
            raise ExitStatePersistenceError(
                "SELL broker identity conflicts "
                "with durable order"
            )

        if (
            existing.broker_order_id
            and existing.broker_order_id
            != reference.order_id
        ):
            raise ExitStatePersistenceError(
                "SELL broker order identity conflicts "
                "with durable order"
            )

        existing.broker_name = (
            reference.broker_name
        )

        existing.broker_order_id = (
            reference.order_id
        )

    @classmethod
    def _validate_snapshot_identity(
        cls,
        *,
        intent: ExitOrderIntent,
        existing: OrderRecord,
        snapshot: ExitOrderSnapshot,
    ) -> None:
        if snapshot.quantity != intent.quantity:
            raise ExitStatePersistenceError(
                "broker SELL snapshot quantity "
                "does not match SELL intent"
            )

        if (
            existing.broker_name
            and existing.broker_name
            != snapshot.broker_reference.broker_name
        ):
            raise ExitStatePersistenceError(
                "broker SELL snapshot broker conflicts "
                "with durable order"
            )

        if (
            existing.broker_order_id
            and existing.broker_order_id
            != snapshot.broker_reference.order_id
        ):
            raise ExitStatePersistenceError(
                "broker SELL snapshot order ID conflicts "
                "with durable order"
            )

    @staticmethod
    def _ordered_fills(
        fills: tuple[
            OrderFillRecord,
            ...
        ],
    ) -> tuple[
        OrderFillRecord,
        ...
    ]:
        return tuple(
            sorted(
                fills,
                key=lambda fill: (
                    fill.filled_at,
                    fill.fill_id,
                ),
            )
        )

    @staticmethod
    def _pending_notional(
        *,
        fills: tuple[
            OrderFillRecord,
            ...
        ],
        already_applied: int,
    ) -> float:
        remaining_skip = (
            already_applied
        )

        pending_notional = 0.0

        for fill in fills:
            quantity = fill.quantity

            if remaining_skip >= quantity:
                remaining_skip -= quantity
                continue

            unapplied_quantity = (
                quantity
                - remaining_skip
            )

            remaining_skip = 0

            pending_notional += (
                unapplied_quantity
                * fill.price
            )

        if remaining_skip != 0:
            raise ExitStatePersistenceError(
                "PositionRecord applied quantity "
                "cannot be resolved against fill ledger"
            )

        return pending_notional

    @staticmethod
    def _validate_managed_identity(
        *,
        intent: ExitOrderIntent,
        durable: PositionRecord,
        managed: ManagedPosition,
    ) -> None:
        position = managed.position

        if (
            position.position_id.value
            != intent.position_id.value
            or durable.position_id
            != intent.position_id.value
        ):
            raise ExitStatePersistenceError(
                "managed SELL position identity mismatch"
            )

        if (
            managed.risk_id.value
            != durable.risk_id
        ):
            raise ExitStatePersistenceError(
                "managed SELL risk identity mismatch"
            )

        if (
            position.signal_id.value
            != durable.signal_id
        ):
            raise ExitStatePersistenceError(
                "managed SELL signal identity mismatch"
            )

        if (
            position.entry_intent_id.value
            != durable.entry_order_intent_id
        ):
            raise ExitStatePersistenceError(
                "managed SELL entry order identity mismatch"
            )

        if (
            position.security_id
            != durable.security_id
            or position.symbol
            != durable.symbol
            or position.option_type.value
            != durable.option_type
            or position.level.value
            != durable.level
        ):
            raise ExitStatePersistenceError(
                "managed SELL contract identity mismatch"
            )

        if (
            position.quantity
            != durable.original_quantity
        ):
            raise ExitStatePersistenceError(
                "managed SELL original quantity mismatch"
            )

        if not isclose(
            position.entry_price,
            durable.entry_price,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ExitStatePersistenceError(
                "managed SELL entry price mismatch"
            )


class DurableExitExecutionProvider(
    ExitExecutionProvider
):
    """
    Crash-safe wrapper around the real SELL broker provider.

    Ordering:

        durable SELL SUBMITTED
            ->
        delegate.submit_exit()
            ->
        durable broker acknowledgement
    """

    def __init__(
        self,
        *,
        delegate: ExitExecutionProvider,
        persistence:
            SQLAlchemyExitPersistenceService,
    ) -> None:
        self._delegate = delegate
        self._persistence = persistence

    @property
    def broker_name(
        self,
    ) -> str:
        return self._delegate.broker_name

    @property
    def delegate(
        self,
    ) -> ExitExecutionProvider:
        return self._delegate

    @property
    def persistence(
        self,
    ) -> SQLAlchemyExitPersistenceService:
        return self._persistence

    def submit_exit(
        self,
        intent: ExitOrderIntent,
    ) -> ExitExecutionResult:
        """
        Persist first, submit second.

        If delegate submission raises, durable SUBMITTED remains
        recovery-visible.
        """

        self._persistence.persist_pre_broker_submission(
            intent=intent,
            broker_name=self.broker_name,
        )

        result = (
            self._delegate.submit_exit(
                intent
            )
        )

        self._persistence.persist_broker_submission_result(
            intent=intent,
            result=result,
        )

        return result

    def cancel_exit(
        self,
        broker_reference:
            BrokerOrderReference,
    ) -> ExitCancellationResult:
        return self._delegate.cancel_exit(
            broker_reference
        )

    def get_exit_status(
        self,
        broker_reference:
            BrokerOrderReference,
    ) -> ExitOrderSnapshot:
        return self._delegate.get_exit_status(
            broker_reference
        )


__all__ = [
    "DurableExitExecutionProvider",
    "ExitFillDelta",
    "ExitStatePersistenceError",
    "SQLAlchemyExitPersistenceService",
]
