from datetime import datetime
from dataclasses import replace

import pytest

from src.reporting.reporting_types import (
    TradeJournalEntry,
)
from src.reporting.trade_analytics import (
    TradeAnalyticsService,
)


NOW = datetime(
    2026,
    8,
    10,
    15,
    20,
)


def entry(
    *,
    position_id: str,
    realized_pnl: float,
    open_quantity: int,
    closed_quantity: int,
    exit_fill_quantity: int | None = None,
) -> TradeJournalEntry:
    if exit_fill_quantity is None:
        exit_fill_quantity = (
            closed_quantity
        )

    return TradeJournalEntry(
        runtime_id="RUNTIME-001",
        position_id=position_id,
        signal_id=(
            f"SIG-{position_id}"
        ),
        entry_order_intent_id=(
            f"BUY-{position_id}"
        ),
        security_id=(
            f"SEC-{position_id}"
        ),
        symbol="NIFTY-TEST",
        option_type="CALL",
        level="K5",
        original_quantity=65,
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        entry_price=100.0,
        entry_order_status="FILLED",
        entry_filled_quantity=65,
        entry_average_fill_price=100.0,
        exit_order_count=(
            1
            if exit_fill_quantity > 0
            else 0
        ),
        exit_fill_count=(
            1
            if exit_fill_quantity > 0
            else 0
        ),
        exit_filled_quantity=(
            exit_fill_quantity
        ),
        average_exit_price=(
            110.0
            if exit_fill_quantity > 0
            else None
        ),
        realized_pnl=realized_pnl,
        latest_unrealized_pnl=0.0,
        latest_total_pnl=realized_pnl,
        latest_ltp=None,
        latest_pnl_at=None,
        state=(
            "CLOSED"
            if open_quantity == 0
            else "OPEN"
        ),
        opened_at=NOW,
        closed_at=(
            NOW
            if open_quantity == 0
            else None
        ),
        exit_persistence_in_sync=(
            exit_fill_quantity
            == closed_quantity
        ),
    )


def test_runtime_analytics_win_loss_metrics():
    service = TradeAnalyticsService()

    result = service.summarize(
        runtime_id="RUNTIME-001",
        entries=(
            entry(
                position_id="P1",
                realized_pnl=650.0,
                open_quantity=0,
                closed_quantity=65,
            ),
            entry(
                position_id="P2",
                realized_pnl=-325.0,
                open_quantity=0,
                closed_quantity=65,
            ),
            entry(
                position_id="P3",
                realized_pnl=0.0,
                open_quantity=0,
                closed_quantity=65,
            ),
        ),
        calculated_at=NOW,
    )

    assert result.position_count == 3
    assert result.closed_position_count == 3

    assert result.winning_position_count == 1
    assert result.losing_position_count == 1
    assert result.breakeven_position_count == 1

    assert result.realized_pnl == 325.0
    assert result.gross_profit == 650.0
    assert result.gross_loss == 325.0

    assert (
        result.win_rate_percent
        == pytest.approx(
            100.0 / 3.0
        )
    )

    assert result.profit_factor == 2.0
    assert result.largest_win == 650.0
    assert result.largest_loss == -325.0


def test_open_position_not_counted_as_completed_trade():
    service = TradeAnalyticsService()

    result = service.summarize(
        runtime_id="RUNTIME-001",
        entries=(
            entry(
                position_id="P1",
                realized_pnl=0.0,
                open_quantity=65,
                closed_quantity=0,
            ),
        ),
        calculated_at=NOW,
    )

    assert result.position_count == 1
    assert result.open_position_count == 1
    assert result.closed_position_count == 0

    assert result.win_rate_percent == 0.0
    assert result.profit_factor is None


def test_partial_realized_pnl_is_in_runtime_total():
    service = TradeAnalyticsService()

    partial = entry(
        position_id="P1",
        realized_pnl=250.0,
        open_quantity=40,
        closed_quantity=25,
    )

    result = service.summarize(
        runtime_id="RUNTIME-001",
        entries=(
            partial,
        ),
        calculated_at=NOW,
    )

    assert result.realized_pnl == 250.0

    assert result.open_position_count == 1
    assert result.closed_position_count == 0


def test_exit_durability_mismatch_is_counted():
    service = TradeAnalyticsService()

    inconsistent = entry(
        position_id="P1",
        realized_pnl=0.0,
        open_quantity=65,
        closed_quantity=0,
        exit_fill_quantity=25,
    )

    result = service.summarize(
        runtime_id="RUNTIME-001",
        entries=(
            inconsistent,
        ),
        calculated_at=NOW,
    )

    assert (
        result.exit_persistence_mismatch_count
        == 1
    )

    assert (
        result.total_exit_filled_quantity
        == 25
    )

    assert result.total_closed_quantity == 0


def test_mixed_runtime_entries_are_rejected():
    service = TradeAnalyticsService()

    wrong_runtime = replace(
        entry(
            position_id="P1",
            realized_pnl=0.0,
            open_quantity=65,
            closed_quantity=0,
        ),
        runtime_id="OTHER-RUNTIME",
    )

    with pytest.raises(
        ValueError,
        match="runtime_id",
    ):
        service.summarize(
            runtime_id="RUNTIME-001",
            entries=(
                wrong_runtime,
            ),
            calculated_at=NOW,
        )
