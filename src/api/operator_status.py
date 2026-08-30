"""
Coherent transport-neutral M13 operator status projection.

This module aggregates existing M13 read services and the exact
M10 durable trading-control state. It owns no broker operation,
repository, registry, execution workflow, risk policy, or
trading state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.api.api_types import (
    OperatorSnapshot,
)
from src.api.operator_account import (
    OperatorAccountView,
)
from src.api.operator_control import (
    OperatorControlStateView,
)
from src.app.trading_control import (
    TradingControlSnapshot,
    TradingControlState,
)


class OperatorSnapshotCapturePort(
    Protocol,
):
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorSnapshot:
        ...


class OperatorAccountCapturePort(
    Protocol,
):
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorAccountView:
        ...


class OperatorControlSnapshotReader(
    Protocol,
):
    @property
    def snapshot(
        self,
    ) -> TradingControlSnapshot:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorStatusView:
    """
    One coherent operator-facing status capture.

    All timestamped M13 read services receive the same captured_at
    value. Durable control truth is read exactly once from the
    authoritative M10 owner.
    """

    snapshot: OperatorSnapshot
    account: OperatorAccountView
    control: OperatorControlStateView

    captured_at: datetime


class OperatorStatusService:
    """
    Aggregate existing authoritative owners into one M13 status.

    This service performs projection only.
    """

    def __init__(
        self,
        *,
        snapshot:
            OperatorSnapshotCapturePort,
        account:
            OperatorAccountCapturePort,
        control:
            OperatorControlSnapshotReader,
    ) -> None:
        self._snapshot = snapshot
        self._account = account
        self._control = control

    @property
    def snapshot(
        self,
    ) -> OperatorSnapshotCapturePort:
        return self._snapshot

    @property
    def account(
        self,
    ) -> OperatorAccountCapturePort:
        return self._account

    @property
    def control(
        self,
    ) -> OperatorControlSnapshotReader:
        return self._control

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorStatusView:
        if type(captured_at) is not datetime:
            raise TypeError(
                "captured_at must be datetime"
            )

        # Read each established owner exactly once.
        snapshot = self._snapshot.capture(
            captured_at=captured_at
        )

        account = self._account.capture(
            captured_at=captured_at
        )

        control = self._control.snapshot

        if not isinstance(
            snapshot,
            OperatorSnapshot,
        ):
            raise TypeError(
                "snapshot owner returned invalid "
                "OperatorSnapshot"
            )

        if not isinstance(
            account,
            OperatorAccountView,
        ):
            raise TypeError(
                "account owner returned invalid "
                "OperatorAccountView"
            )

        if not isinstance(
            control,
            TradingControlSnapshot,
        ):
            raise TypeError(
                "control owner returned invalid "
                "TradingControlSnapshot"
            )

        # A consolidated status must never silently combine
        # different broker accounts.
        if control.broker != account.broker:
            raise ValueError(
                "operator status broker identity mismatch"
            )

        if (
            control.account_id
            != account.account_id
        ):
            raise ValueError(
                "operator status account identity mismatch"
            )

        control_view = (
            OperatorControlStateView(
                state=control.state.value,
                changed_at=control.changed_at,
                new_entries_allowed=(
                    control.state
                    is TradingControlState.ACTIVE
                ),
            )
        )

        return OperatorStatusView(
            snapshot=snapshot,
            account=account,
            control=control_view,
            captured_at=captured_at,
        )


__all__ = [
    "OperatorAccountCapturePort",
    "OperatorControlSnapshotReader",
    "OperatorSnapshotCapturePort",
    "OperatorStatusService",
    "OperatorStatusView",
]
