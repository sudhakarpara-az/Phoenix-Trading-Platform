
"""
Phoenix M10 durable application trading control.

This module owns the persistent account-scoped operator control
state used by EXIT AND STOP.

This first corrective slice deliberately owns only:

    - durable ACTIVE / EXIT_AND_STOP state;
    - fail-closed recovery;
    - new-entry blocking through the existing DailyRiskManager;
    - explicit resume.

Pending BUY cancellation and open-position liquidation are
orchestrated in later corrective slices before the command is
exposed through M13.
"""

from __future__ import annotations

from src.services.scheduler import (
    TradingDayCloseReadiness,
)

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import RLock
from typing import Protocol


class TradingControlState(
    str,
    Enum,
):
    ACTIVE = "ACTIVE"
    EXIT_AND_STOP = "EXIT_AND_STOP"


@dataclass(
    frozen=True,
    slots=True,
)
class TradingControlSnapshot:
    broker: str
    account_id: str

    state: TradingControlState

    changed_at: datetime | None
    message: str | None


@dataclass(
    frozen=True,
    slots=True,
)
class TradingControlRecordData:
    """
    Persistence-neutral immutable representation of one
    durable M10 trading-control record.

    SQLAlchemy ORM objects must not cross into
    TradingControlService.
    """

    broker: str
    account_id: str
    state: str
    changed_at: datetime

    message: str | None = None
    control_id: str = ""


class TradingControlRepositoryPort(
    Protocol,
):
    def get_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> TradingControlRecordData | None:
        ...

    def set_for_account(
        self,
        *,
        broker: str,
        account_id: str,
        state: str,
        message: str | None,
        changed_at: datetime,
    ) -> TradingControlRecordData:
        ...


class ManualEntryLockPort(
    Protocol,
):
    def set_manual_lock(
        self,
        *,
        message: str | None = None,
    ) -> None:
        ...

    def clear_manual_lock(
        self,
    ) -> None:
        ...

    def is_manually_locked(
        self,
    ) -> bool:
        ...


class TradingControlError(
    RuntimeError,
):
    pass


class TradingControlService:
    """
    Durable account-level application control owner.

    Safety ordering:

    EXIT_AND_STOP:
        1. persist STOP
        2. publish internal STOP snapshot
        3. activate exact existing DailyRiskManager manual lock

    RESUME:
        1. persist ACTIVE
        2. publish internal ACTIVE snapshot
        3. clear exact existing DailyRiskManager manual lock

    Therefore persistence failure never silently changes the
    current entry permission.
    """

    def __init__(
        self,
        *,
        broker: str,
        account_id: str,
        repository: TradingControlRepositoryPort,
        manual_entry_lock: ManualEntryLockPort,
    ) -> None:
        resolved_broker = broker.strip()
        resolved_account_id = account_id.strip()

        if not resolved_broker:
            raise ValueError(
                "broker cannot be empty"
            )

        if not resolved_account_id:
            raise ValueError(
                "account_id cannot be empty"
            )

        self._broker = resolved_broker
        self._account_id = resolved_account_id

        self._repository = repository
        self._manual_entry_lock = (
            manual_entry_lock
        )

        # None means recovery has not yet established durable
        # truth. can_accept_new_entries() therefore fails closed.
        self._snapshot: (
            TradingControlSnapshot | None
        ) = None

        self._lock = RLock()

    @property
    def broker(
        self,
    ) -> str:
        return self._broker

    @property
    def account_id(
        self,
    ) -> str:
        return self._account_id

    @property
    def repository(
        self,
    ) -> TradingControlRepositoryPort:
        return self._repository

    @property
    def manual_entry_lock(
        self,
    ) -> ManualEntryLockPort:
        return self._manual_entry_lock

    @property
    def snapshot(
        self,
    ) -> TradingControlSnapshot:
        with self._lock:
            if self._snapshot is None:
                raise TradingControlError(
                    "trading control has not been restored"
                )

            return self._snapshot

    def can_accept_new_entries(
        self,
    ) -> bool:
        """
        Fail closed until durable state has been restored.
        """

        with self._lock:
            return (
                self._snapshot is not None
                and self._snapshot.state
                is TradingControlState.ACTIVE
            )

    def is_exit_and_stop_active(
        self,
    ) -> bool:
        with self._lock:
            return (
                self._snapshot is not None
                and self._snapshot.state
                is TradingControlState.EXIT_AND_STOP
            )

    def restore(
        self,
    ) -> TradingControlSnapshot:
        """
        Restore account control before live entry processing.

        No durable record means the account has never been
        stopped and therefore starts ACTIVE.

        An EXIT_AND_STOP record immediately re-applies the
        existing DailyRiskManager manual entry lock.
        """

        with self._lock:
            record = (
                self._repository
                .get_for_account(
                    broker=self._broker,
                    account_id=self._account_id,
                )
            )

            if record is None:
                snapshot = TradingControlSnapshot(
                    broker=self._broker,
                    account_id=self._account_id,
                    state=TradingControlState.ACTIVE,
                    changed_at=None,
                    message=None,
                )

                self._snapshot = snapshot

                return snapshot

            snapshot = (
                self._snapshot_from_record(
                    record
                )
            )

            # Publish recovered durable truth before any
            # downstream action.
            self._snapshot = snapshot

            if (
                snapshot.state
                is TradingControlState.EXIT_AND_STOP
            ):
                self._manual_entry_lock.set_manual_lock(
                    message=snapshot.message
                )

            return snapshot

    def activate_exit_and_stop(
        self,
        *,
        changed_at: datetime,
        message: str | None = None,
    ) -> TradingControlSnapshot:
        self._validate_changed_at(
            changed_at
        )

        resolved_message = (
            self._normalize_message(
                message
            )
        )

        with self._lock:
            persisted = (
                self._repository
                .set_for_account(
                    broker=self._broker,
                    account_id=self._account_id,
                    state=(
                        TradingControlState
                        .EXIT_AND_STOP
                        .value
                    ),
                    message=resolved_message,
                    changed_at=changed_at,
                )
            )

            snapshot = (
                self._snapshot_from_record(
                    persisted
                )
            )

            if (
                snapshot.state
                is not TradingControlState
                .EXIT_AND_STOP
            ):
                raise TradingControlError(
                    "persisted STOP state was not "
                    "EXIT_AND_STOP"
                )

            # Durable truth is authoritative even if the local
            # lock application unexpectedly fails.
            self._snapshot = snapshot

            self._manual_entry_lock.set_manual_lock(
                message=resolved_message
            )

            return snapshot

    def resume(
        self,
        *,
        changed_at: datetime,
        message: str | None = None,
    ) -> TradingControlSnapshot:
        self._validate_changed_at(
            changed_at
        )

        resolved_message = (
            self._normalize_message(
                message
            )
        )

        with self._lock:
            persisted = (
                self._repository
                .set_for_account(
                    broker=self._broker,
                    account_id=self._account_id,
                    state=(
                        TradingControlState
                        .ACTIVE
                        .value
                    ),
                    message=resolved_message,
                    changed_at=changed_at,
                )
            )

            snapshot = (
                self._snapshot_from_record(
                    persisted
                )
            )

            if (
                snapshot.state
                is not TradingControlState.ACTIVE
            ):
                raise TradingControlError(
                    "persisted RESUME state was not ACTIVE"
                )

            self._snapshot = snapshot

            self._manual_entry_lock.clear_manual_lock()

            return snapshot

    def _snapshot_from_record(
        self,
        record: TradingControlRecordData,
    ) -> TradingControlSnapshot:
        if (
            record.broker != self._broker
            or record.account_id
            != self._account_id
        ):
            raise TradingControlError(
                "durable trading-control identity mismatch"
            )

        try:
            state = TradingControlState(
                record.state
            )

        except ValueError as exc:
            raise TradingControlError(
                "unsupported durable trading-control state"
            ) from exc

        if type(record.changed_at) is not datetime:
            raise TradingControlError(
                "durable trading-control changed_at "
                "must be datetime"
            )

        return TradingControlSnapshot(
            broker=record.broker,
            account_id=record.account_id,
            state=state,
            changed_at=record.changed_at,
            message=record.message,
        )

    @staticmethod
    def _validate_changed_at(
        changed_at: datetime,
    ) -> None:
        if type(changed_at) is not datetime:
            raise TypeError(
                "changed_at must be datetime"
            )

    @staticmethod
    def _normalize_message(
        message: str | None,
    ) -> str | None:
        if message is None:
            return None

        resolved = message.strip()

        if not resolved:
            raise ValueError(
                "message cannot be empty"
            )

        return resolved



class TradingControlStatePort(
    Protocol,
):
    """
    Durable M10 STOP-state owner required by the command layer.
    """

    def activate_exit_and_stop(
        self,
        *,
        changed_at: datetime,
        message: str | None = None,
    ) -> TradingControlSnapshot:
        ...

    def resume(
        self,
        *,
        changed_at: datetime,
        message: str | None = None,
    ) -> TradingControlSnapshot:
        ...


class PendingEntryControlPort(
    Protocol,
):
    """
    Existing T14 pending-BUY cancellation boundary.
    """

    def cancel_pending_entries(
        self,
        *,
        cancelled_at: datetime,
    ) -> tuple[
        object,
        ...,
    ]:
        ...


class ManualLiquidationControlPort(
    Protocol,
):
    """
    Existing durable MANUAL SELL runtime boundary.
    """

    def liquidate_open_positions(
        self,
        *,
        evaluated_at: datetime,
    ) -> tuple[
        object,
        ...,
    ]:
        ...


class CloseReadinessPort(
    Protocol,
):
    """
    Existing local + durable + broker-wide flatness boundary.
    """

    def evaluate_close_readiness(
        self,
        *,
        evaluated_at: datetime,
    ) -> TradingDayCloseReadiness:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class ExitAndStopCommandResult:
    """
    Result of one complete operator EXIT AND STOP request.

    STOP durability is independent from downstream order
    reconciliation. Therefore a result may require operator
    attention while the durable STOP remains active.
    """

    control: TradingControlSnapshot

    entry_results: tuple[
        object,
        ...,
    ]

    liquidation_results: tuple[
        object,
        ...,
    ]

    readiness: (
        TradingDayCloseReadiness
        | None
    )

    requested_at: datetime

    entry_error: str | None
    liquidation_error: str | None
    readiness_error: str | None

    @property
    def stop_active(
        self,
    ) -> bool:
        return (
            self.control.state
            is TradingControlState
            .EXIT_AND_STOP
        )

    @property
    def flat_confirmed(
        self,
    ) -> bool:
        return (
            self.readiness is not None
            and self.readiness.is_ready
        )

    @property
    def requires_attention(
        self,
    ) -> bool:
        return (
            self.entry_error is not None
            or self.liquidation_error
            is not None
            or self.readiness_error
            is not None
            or not self.flat_confirmed
        )


class TradingControlCommandError(
    RuntimeError,
):
    """
    Complete M10 strong-stop command failure.
    """


class TradingControlCommandService:
    """
    Complete M10 EXIT AND STOP orchestration.

    Required safety order:

        1. persist EXIT_AND_STOP and apply entry lock
        2. cancel/reconcile unresolved BUY orders
        3. liquidate/reconcile all open positions
        4. evaluate local + durable + broker flatness

    Any failure after step 1 MUST leave STOP active.

    RESUME is deliberately separate and is permitted only when
    the existing close-readiness owner proves zero open exposure
    and zero unresolved orders.
    """

    def __init__(
        self,
        *,
        trading_control:
            TradingControlStatePort,
        entry_runtime:
            PendingEntryControlPort,
        liquidation_runtime:
            ManualLiquidationControlPort,
        readiness:
            CloseReadinessPort,
    ) -> None:
        self._trading_control = (
            trading_control
        )

        self._entry_runtime = (
            entry_runtime
        )

        self._liquidation_runtime = (
            liquidation_runtime
        )

        self._readiness = (
            readiness
        )

        # Serialize operator STOP / RESUME commands.
        self._lock = RLock()

    @property
    def trading_control(
        self,
    ) -> TradingControlStatePort:
        return self._trading_control

    @property
    def entry_runtime(
        self,
    ) -> PendingEntryControlPort:
        return self._entry_runtime

    @property
    def liquidation_runtime(
        self,
    ) -> ManualLiquidationControlPort:
        return self._liquidation_runtime

    @property
    def readiness(
        self,
    ) -> CloseReadinessPort:
        return self._readiness

    def exit_and_stop(
        self,
        *,
        changed_at: datetime,
        message: str | None = None,
    ) -> ExitAndStopCommandResult:
        """
        Persist STOP first, then unwind BUY/SELL exposure.

        Failure to establish durable STOP propagates immediately
        and prevents any cancellation/liquidation action.

        Once STOP succeeds, downstream failures are isolated so
        Phoenix can continue attempting the remaining safety
        phases. The returned result reports whether flatness was
        ultimately proven.
        """

        self._validate_datetime(
            changed_at
        )

        with self._lock:

            # ------------------------------------------------
            # Phase 1 ? durable authoritative STOP.
            #
            # DO NOT catch this exception. Without proven STOP
            # durability/entry blocking we must not represent the
            # strong-stop command as having started successfully.
            # ------------------------------------------------

            control = (
                self._trading_control
                .activate_exit_and_stop(
                    changed_at=changed_at,
                    message=message,
                )
            )

            if not isinstance(
                control,
                TradingControlSnapshot,
            ):
                raise TradingControlCommandError(
                    "STOP owner returned invalid snapshot"
                )

            if (
                control.state
                is not TradingControlState
                .EXIT_AND_STOP
            ):
                raise TradingControlCommandError(
                    "STOP owner did not establish "
                    "EXIT_AND_STOP"
                )

            # ------------------------------------------------
            # Phase 2 ? pending BUY cancellation/reconciliation.
            # ------------------------------------------------

            entry_results: tuple[
                object,
                ...,
            ] = ()

            entry_error: (
                str | None
            ) = None

            try:
                candidate = (
                    self._entry_runtime
                    .cancel_pending_entries(
                        cancelled_at=changed_at,
                    )
                )

                if not isinstance(
                    candidate,
                    tuple,
                ):
                    raise TypeError(
                        "pending-entry control must "
                        "return tuple"
                    )

                entry_results = candidate

            except Exception as exc:
                entry_error = (
                    self._phase_error(
                        phase=(
                            "pending BUY cancellation"
                        ),
                        error=exc,
                    )
                )

            # ------------------------------------------------
            # Phase 3 ? open-position MANUAL liquidation.
            #
            # This still runs when BUY cancellation reported an
            # unexpected error. Existing managed positions must
            # not be abandoned because another phase failed.
            # ------------------------------------------------

            liquidation_results: tuple[
                object,
                ...,
            ] = ()

            liquidation_error: (
                str | None
            ) = None

            try:
                candidate = (
                    self._liquidation_runtime
                    .liquidate_open_positions(
                        evaluated_at=changed_at,
                    )
                )

                if not isinstance(
                    candidate,
                    tuple,
                ):
                    raise TypeError(
                        "manual-liquidation control "
                        "must return tuple"
                    )

                liquidation_results = (
                    candidate
                )

            except Exception as exc:
                liquidation_error = (
                    self._phase_error(
                        phase=(
                            "manual liquidation"
                        ),
                        error=exc,
                    )
                )

            # ------------------------------------------------
            # Phase 4 ? authoritative flatness proof.
            #
            # Existing readiness combines local M07/T14 state,
            # durable unresolved orders and Dhan account truth.
            # ------------------------------------------------

            readiness: (
                TradingDayCloseReadiness
                | None
            ) = None

            readiness_error: (
                str | None
            ) = None

            try:
                candidate_readiness = (
                    self._readiness
                    .evaluate_close_readiness(
                        evaluated_at=changed_at,
                    )
                )

                if not isinstance(
                    candidate_readiness,
                    TradingDayCloseReadiness,
                ):
                    raise TypeError(
                        "readiness owner returned "
                        "invalid result"
                    )

                readiness = (
                    candidate_readiness
                )

            except Exception as exc:
                readiness_error = (
                    self._phase_error(
                        phase=(
                            "flatness verification"
                        ),
                        error=exc,
                    )
                )

            return ExitAndStopCommandResult(
                control=control,
                entry_results=(
                    entry_results
                ),
                liquidation_results=(
                    liquidation_results
                ),
                readiness=readiness,
                requested_at=changed_at,
                entry_error=entry_error,
                liquidation_error=(
                    liquidation_error
                ),
                readiness_error=(
                    readiness_error
                ),
            )

    def resume(
        self,
        *,
        changed_at: datetime,
        message: str | None = None,
    ) -> TradingControlSnapshot:
        """
        Explicitly resume entry processing only after Phoenix and
        Dhan both prove the account is flat and has no unresolved
        orders.

        The durable TradingControlService itself remains the owner
        of ACTIVE persistence and DailyRiskManager unlock ordering.
        """

        self._validate_datetime(
            changed_at
        )

        with self._lock:

            try:
                readiness = (
                    self._readiness
                    .evaluate_close_readiness(
                        evaluated_at=changed_at,
                    )
                )

            except Exception as exc:
                raise TradingControlCommandError(
                    "cannot RESUME because flatness "
                    "could not be established"
                ) from exc

            if not isinstance(
                readiness,
                TradingDayCloseReadiness,
            ):
                raise TradingControlCommandError(
                    "cannot RESUME because readiness "
                    "returned invalid result"
                )

            if not readiness.is_ready:
                raise TradingControlCommandError(
                    "cannot RESUME while open positions "
                    "or unresolved orders remain"
                )

            snapshot = (
                self._trading_control
                .resume(
                    changed_at=changed_at,
                    message=message,
                )
            )

            if not isinstance(
                snapshot,
                TradingControlSnapshot,
            ):
                raise TradingControlCommandError(
                    "RESUME owner returned invalid snapshot"
                )

            if (
                snapshot.state
                is not TradingControlState.ACTIVE
            ):
                raise TradingControlCommandError(
                    "RESUME owner did not establish ACTIVE"
                )

            return snapshot

    @staticmethod
    def _validate_datetime(
        value: datetime,
    ) -> None:
        if type(value) is not datetime:
            raise TypeError(
                "changed_at must be a datetime"
            )

    @staticmethod
    def _phase_error(
        *,
        phase: str,
        error: Exception,
    ) -> str:
        """
        Deliberately avoid copying arbitrary broker exception text
        into the command result. M13 may later expose this result
        to an operator surface.
        """

        return (
            f"{phase} failed: "
            f"{type(error).__name__}"
        )


__all__ = [
    "ManualEntryLockPort",
    "TradingControlError",
    "TradingControlRecordData",
    "TradingControlRepositoryPort",
    "TradingControlService",
    "TradingControlSnapshot",
    "TradingControlState",
]

__all__ += [
    "CloseReadinessPort",
    "ExitAndStopCommandResult",
    "ManualLiquidationControlPort",
    "PendingEntryControlPort",
    "TradingControlCommandError",
    "TradingControlCommandService",
    "TradingControlStatePort",
]
