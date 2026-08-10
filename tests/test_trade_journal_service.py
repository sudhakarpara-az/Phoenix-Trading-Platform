from __future__ import annotations

from datetime import datetime

import pytest

from src.database.schema import (
    OrderFillRecord,
    OrderRecord,
    PnLSnapshotRecord,
    PositionRecord,
)
from src.reporting.trade_journal import (
    TradeJournalIntegrityError,
    TradeJournalService,
)


NOW = datetime(
    2026,
    8,
    10,
    9,
    30,
)

LATER = datetime(
    2026,
    8,
    10,
    10,
    0,
)

CLOSED = datetime(
    2026,
    8,
    10,
    10,
    15,
)


def order(
    *,
    intent_id: str,
    side: str,
    position_id: str,
    quantity: int = 65,
    filled_quantity: int = 65,
    average_fill_price: float = 100.0,
) -> OrderRecord:
    return OrderRecord(
        order_intent_id=intent_id,
        runtime_id="RUNTIME-001",
        signal_id="SIGNAL-001",
        position_id=position_id,
        security_id="SEC-001",
        symbol="NIFTY-TEST",
        side=side,
        order_type="LIMIT",
        reason=(
            "ENTRY"
            if side == "BUY"
            else "TARGET"
        ),
        quantity=quantity,
        limit_price=average_fill_price,
        execution_mode="LIVE",
        status="FILLED",
        broker_name="DHAN",
        broker_order_id=(
            f"BROKER-{intent_id}"
        ),
        filled_quantity=filled_quantity,
        average_fill_price=(
            average_fill_price
        ),
        created_at=NOW,
        submitted_at=NOW,
        updated_at=LATER,
    )


def position(
    *,
    open_quantity: int = 0,
    closed_quantity: int = 65,
    realized_pnl: float = 650.0,
) -> PositionRecord:
    return PositionRecord(
        position_id="POS-001",
        risk_id="RISK-001",
        runtime_id="RUNTIME-001",
        signal_id="SIGNAL-001",
        entry_order_intent_id="BUY-001",
        security_id="SEC-001",
        symbol="NIFTY-TEST",
        option_type="CALL",
        level="K5",
        original_quantity=65,
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        entry_price=100.0,
        realized_pnl=realized_pnl,
        state=(
            "CLOSED"
            if open_quantity == 0
            else "PARTIALLY_EXITED"
        ),
        stop_price=85.0,
        stop_risk_points=15.0,
        stop_state="ARMED",
        executable_target_price=110.0,
        mapped_target_price=112.0,
        booking_zone_start=109.0,
        booking_zone_end=110.0,
        target_state="ARMED",
        opened_at=NOW,
        updated_at=CLOSED,
        closed_at=(
            CLOSED
            if open_quantity == 0
            else None
        ),
    )


def fill(
    *,
    fill_id: str,
    quantity: int,
    price: float,
) -> OrderFillRecord:
    return OrderFillRecord(
        fill_id=fill_id,
        order_intent_id="SELL-001",
        broker_trade_id=(
            f"TRADE-{fill_id}"
        ),
        quantity=quantity,
        price=price,
        filled_at=CLOSED,
    )


def pnl(
    *,
    snapshot_id: str,
    unrealized_pnl: float,
    total_pnl: float,
    ltp: float,
    captured_at: datetime,
) -> PnLSnapshotRecord:
    return PnLSnapshotRecord(
        snapshot_id=snapshot_id,
        runtime_id="RUNTIME-001",
        position_id="POS-001",
        realized_pnl=0.0,
        unrealized_pnl=unrealized_pnl,
        total_pnl=total_pnl,
        unrealized_points=(
            ltp - 100.0
        ),
        ltp=ltp,
        open_quantity=65,
        captured_at=captured_at,
    )


class FakeOrderRepository:
    def __init__(
        self,
        records: tuple[
            OrderRecord,
            ...,
        ],
    ) -> None:
        self.records = records

    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        OrderRecord,
        ...,
    ]:
        return tuple(
            item
            for item in self.records
            if item.runtime_id == runtime_id
        )


class FakePositionRepository:
    def __init__(
        self,
        records: tuple[
            PositionRecord,
            ...,
        ],
    ) -> None:
        self.records = records

    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        PositionRecord,
        ...,
    ]:
        return tuple(
            item
            for item in self.records
            if item.runtime_id == runtime_id
        )


class FakeFillRepository:
    def __init__(
        self,
        records: tuple[
            OrderFillRecord,
            ...,
        ],
    ) -> None:
        self.records = records

    def list_by_order(
        self,
        order_intent_id: str,
    ) -> tuple[
        OrderFillRecord,
        ...,
    ]:
        return tuple(
            item
            for item in self.records
            if (
                item.order_intent_id
                == order_intent_id
            )
        )


class FakePnLRepository:
    def __init__(
        self,
        records: tuple[
            PnLSnapshotRecord,
            ...,
        ],
    ) -> None:
        self.records = records

    def list_by_position(
        self,
        position_id: str,
    ) -> tuple[
        PnLSnapshotRecord,
        ...,
    ]:
        return tuple(
            item
            for item in self.records
            if item.position_id == position_id
        )


def service(
    *,
    orders: tuple[
        OrderRecord,
        ...,
    ],
    positions: tuple[
        PositionRecord,
        ...,
    ],
    fills: tuple[
        OrderFillRecord,
        ...,
    ] = (),
    pnls: tuple[
        PnLSnapshotRecord,
        ...,
    ] = (),
) -> TradeJournalService:
    return TradeJournalService(
        order_repository=(
            FakeOrderRepository(
                orders
            )
        ),
        order_fill_repository=(
            FakeFillRepository(
                fills
            )
        ),
        position_repository=(
            FakePositionRepository(
                positions
            )
        ),
        pnl_repository=(
            FakePnLRepository(
                pnls
            )
        ),
    )


def test_closed_position_projects_actual_exit_fills():
    journal = service(
        orders=(
            order(
                intent_id="BUY-001",
                side="BUY",
                position_id="POS-001",
                average_fill_price=100.0,
            ),
            order(
                intent_id="SELL-001",
                side="SELL",
                position_id="POS-001",
                average_fill_price=110.0,
            ),
        ),
        positions=(
            position(),
        ),
        fills=(
            fill(
                fill_id="FILL-1",
                quantity=25,
                price=109.0,
            ),
            fill(
                fill_id="FILL-2",
                quantity=40,
                price=111.0,
            ),
        ),
    )

    entries = journal.list_runtime(
        "RUNTIME-001"
    )

    assert len(
        entries
    ) == 1

    entry = entries[0]

    assert entry.position_id == "POS-001"
    assert entry.exit_order_count == 1
    assert entry.exit_fill_count == 2
    assert entry.exit_filled_quantity == 65

    expected_average = (
        (
            25 * 109.0
            + 40 * 111.0
        )
        / 65
    )

    assert (
        entry.average_exit_price
        == pytest.approx(
            expected_average
        )
    )

    assert entry.realized_pnl == 650.0

    assert (
        entry.exit_persistence_in_sync
        is True
    )


def test_latest_pnl_snapshot_selected_by_timestamp():
    journal = service(
        orders=(
            order(
                intent_id="BUY-001",
                side="BUY",
                position_id="POS-001",
            ),
        ),
        positions=(
            position(
                open_quantity=65,
                closed_quantity=0,
                realized_pnl=0.0,
            ),
        ),
        pnls=(
            pnl(
                snapshot_id="PNL-2",
                unrealized_pnl=780.0,
                total_pnl=780.0,
                ltp=112.0,
                captured_at=LATER,
            ),
            pnl(
                snapshot_id="PNL-1",
                unrealized_pnl=650.0,
                total_pnl=650.0,
                ltp=110.0,
                captured_at=NOW,
            ),
        ),
    )

    entry = journal.list_runtime(
        "RUNTIME-001"
    )[0]

    assert entry.latest_ltp == 112.0
    assert entry.latest_unrealized_pnl == 780.0
    assert entry.latest_total_pnl == 780.0
    assert entry.latest_pnl_at == LATER


def test_fill_position_durability_gap_is_exposed_not_repaired():
    journal = service(
        orders=(
            order(
                intent_id="BUY-001",
                side="BUY",
                position_id="POS-001",
            ),
            order(
                intent_id="SELL-001",
                side="SELL",
                position_id="POS-001",
                quantity=65,
                filled_quantity=25,
                average_fill_price=110.0,
            ),
        ),
        positions=(
            position(
                open_quantity=65,
                closed_quantity=0,
                realized_pnl=0.0,
            ),
        ),
        fills=(
            fill(
                fill_id="FILL-1",
                quantity=25,
                price=110.0,
            ),
        ),
    )

    entry = journal.list_runtime(
        "RUNTIME-001"
    )[0]

    assert entry.closed_quantity == 0
    assert entry.exit_filled_quantity == 25

    assert (
        entry.exit_persistence_in_sync
        is False
    )


def test_missing_entry_order_fails_closed():
    journal = service(
        orders=(),
        positions=(
            position(),
        ),
    )

    with pytest.raises(
        TradeJournalIntegrityError,
        match="no matching entry OrderRecord",
    ):
        journal.list_runtime(
            "RUNTIME-001"
        )


def test_runtime_entries_are_sorted_by_open_time():
    second = position()
    second.position_id = "POS-002"
    second.risk_id = "RISK-002"
    second.entry_order_intent_id = "BUY-002"
    second.opened_at = LATER

    journal = service(
        orders=(
            order(
                intent_id="BUY-001",
                side="BUY",
                position_id="POS-001",
            ),
            order(
                intent_id="BUY-002",
                side="BUY",
                position_id="POS-002",
            ),
        ),
        positions=(
            second,
            position(),
        ),
    )

    entries = journal.list_runtime(
        "RUNTIME-001"
    )

    assert [
        item.position_id
        for item in entries
    ] == [
        "POS-001",
        "POS-002",
    ]
