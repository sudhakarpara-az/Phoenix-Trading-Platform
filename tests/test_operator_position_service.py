from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from src.api.operator_positions import (
    OperatorPositionService,
)


CAPTURED_AT = datetime(
    2026,
    8,
    31,
    10,
    30,
)

CREATED_AT = datetime(
    2026,
    8,
    31,
    9,
    35,
)

UPDATED_AT = datetime(
    2026,
    8,
    31,
    10,
    29,
)

MARKED_AT = datetime(
    2026,
    8,
    31,
    10,
    29,
)


class FakeId:
    def __init__(
        self,
        value: str,
    ) -> None:
        self.value = value


class FakeState:
    def __init__(
        self,
        value: str,
    ) -> None:
        self.value = value


class FakePosition:
    def __init__(
        self,
        *,
        position_id: str,
        risk_id: str,
        symbol: str,
        security_id: str,
        entry_price: float,
        open_quantity: int,
        closed_quantity: int,
        realized_pnl: float,
    ) -> None:
        self.position_id = FakeId(
            position_id
        )

        self.risk_id = FakeId(
            risk_id
        )

        self.symbol = symbol
        self.security_id = security_id

        self.lot_size = 65

        self.entry_price = (
            entry_price
        )

        self.original_quantity = (
            open_quantity
            + closed_quantity
        )

        self.open_quantity = (
            open_quantity
        )

        self.closed_quantity = (
            closed_quantity
        )

        self.realized_pnl = (
            realized_pnl
        )

        self.state = FakeState(
            "PARTIALLY_EXITED"
            if closed_quantity > 0
            else "OPEN"
        )

        self.created_at = CREATED_AT
        self.updated_at = UPDATED_AT


class FakePnL:
    def __init__(
        self,
        *,
        realized_pnl: float,
        unrealized_pnl: float,
        total_pnl: float,
        unrealized_points: float,
        latest_ltp: float | None,
    ) -> None:
        self.realized_pnl = (
            realized_pnl
        )

        self.unrealized_pnl = (
            unrealized_pnl
        )

        self.total_pnl = (
            total_pnl
        )

        self.unrealized_points = (
            unrealized_points
        )

        self.latest_ltp = latest_ltp

        self.latest_mark_at = (
            MARKED_AT
            if latest_ltp
            is not None
            else None
        )


class FakeRegistry:
    def __init__(
        self,
        positions: tuple[
            Any,
            ...,
        ],
    ) -> None:
        self.positions = positions
        self.calls = 0

    def open_positions(
        self,
    ) -> tuple[
        Any,
        ...,
    ]:
        self.calls += 1

        return self.positions


class FakePnLTracker:
    def __init__(
        self,
        states: dict[
            str,
            Any,
        ],
    ) -> None:
        self.states = states
        self.calls: list[
            str
        ] = []

    def get(
        self,
        position_id: Any,
    ) -> Any:
        self.calls.append(
            position_id.value
        )

        return self.states.get(
            position_id.value
        )


def test_position_projection_preserves_exact_owners() -> None:
    registry = FakeRegistry(
        ()
    )

    pnl_tracker = FakePnLTracker(
        {}
    )

    service = OperatorPositionService(
        registry=registry,
        pnl_tracker=pnl_tracker,
    )

    assert service.registry is registry
    assert (
        service.pnl_tracker
        is pnl_tracker
    )


def test_position_projection_maps_open_positions_and_pnl() -> None:
    first = FakePosition(
        position_id="POS-1",
        risk_id="RISK-1",
        symbol="NIFTY-CE",
        security_id="101",
        entry_price=100.0,
        open_quantity=65,
        closed_quantity=0,
        realized_pnl=0.0,
    )

    second = FakePosition(
        position_id="POS-2",
        risk_id="RISK-2",
        symbol="NIFTY-PE",
        security_id="202",
        entry_price=120.0,
        open_quantity=65,
        closed_quantity=65,
        realized_pnl=325.0,
    )

    registry = FakeRegistry(
        (
            first,
            second,
        )
    )

    pnl_tracker = FakePnLTracker(
        {
            "POS-1": FakePnL(
                realized_pnl=0.0,
                unrealized_pnl=650.0,
                total_pnl=650.0,
                unrealized_points=10.0,
                latest_ltp=110.0,
            ),
            "POS-2": FakePnL(
                realized_pnl=325.0,
                unrealized_pnl=-325.0,
                total_pnl=0.0,
                unrealized_points=-5.0,
                latest_ltp=115.0,
            ),
        }
    )

    service = OperatorPositionService(
        registry=registry,
        pnl_tracker=pnl_tracker,
    )

    result = service.capture(
        captured_at=CAPTURED_AT,
    )

    assert registry.calls == 1

    assert pnl_tracker.calls == [
        "POS-1",
        "POS-2",
    ]

    assert result.open_count == 2

    assert (
        result.open_quantity
        == 130
    )

    assert (
        result.realized_pnl
        == 325.0
    )

    assert (
        result.unrealized_pnl
        == 325.0
    )

    assert (
        result.total_pnl
        == 650.0
    )

    assert (
        result.captured_at
        == CAPTURED_AT
    )

    first_view = (
        result.positions[0]
    )

    assert (
        first_view.position_id
        == "POS-1"
    )

    assert (
        first_view.symbol
        == "NIFTY-CE"
    )

    assert (
        first_view.latest_ltp
        == 110.0
    )

    assert (
        first_view.unrealized_pnl
        == 650.0
    )

    assert (
        first_view.total_pnl
        == 650.0
    )

    assert (
        first_view.pnl_available
        is True
    )


def test_position_projection_does_not_fabricate_missing_pnl() -> None:
    position = FakePosition(
        position_id="POS-1",
        risk_id="RISK-1",
        symbol="NIFTY-CE",
        security_id="101",
        entry_price=100.0,
        open_quantity=65,
        closed_quantity=0,
        realized_pnl=50.0,
    )

    service = OperatorPositionService(
        registry=FakeRegistry(
            (
                position,
            )
        ),
        pnl_tracker=FakePnLTracker(
            {}
        ),
    )

    result = service.capture(
        captured_at=CAPTURED_AT,
    )

    view = result.positions[0]

    assert (
        view.pnl_available
        is False
    )

    assert view.latest_ltp is None
    assert (
        view.latest_mark_at
        is None
    )

    assert (
        view.unrealized_pnl
        is None
    )

    assert view.total_pnl is None

    assert (
        result.realized_pnl
        == 50.0
    )

    assert (
        result.unrealized_pnl
        == 0.0
    )

    assert (
        result.total_pnl
        == 50.0
    )


def test_position_projection_rejects_non_datetime_capture() -> None:
    registry = FakeRegistry(
        ()
    )

    service = OperatorPositionService(
        registry=registry,
        pnl_tracker=FakePnLTracker(
            {}
        ),
    )

    with pytest.raises(
        TypeError,
        match=(
            "captured_at must be "
            "a datetime"
        ),
    ):
        service.capture(
            captured_at=object(),  # type: ignore[arg-type]
        )

    assert registry.calls == 0
