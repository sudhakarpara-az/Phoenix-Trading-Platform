"""
Phoenix M12 trade analytics.

Analytics operate exclusively on immutable TradeJournalEntry
values. No execution or persistence dependency belongs here.
"""

from __future__ import annotations

from datetime import datetime

from src.reporting.reporting_types import (
    TradeAnalyticsSummary,
    TradeJournalEntry,
)


class TradeAnalyticsService:
    """
    Computes deterministic runtime-level analytics.
    """

    def summarize(
        self,
        *,
        runtime_id: str,
        entries: tuple[
            TradeJournalEntry,
            ...,
        ],
        calculated_at: datetime,
    ) -> TradeAnalyticsSummary:
        if not isinstance(
            runtime_id,
            str,
        ):
            raise TypeError(
                "runtime_id must be str"
            )

        runtime_id = runtime_id.strip()

        if not runtime_id:
            raise ValueError(
                "runtime_id cannot be empty"
            )

        if type(calculated_at) is not datetime:
            raise TypeError(
                "calculated_at must be datetime"
            )

        for entry in entries:
            if entry.runtime_id != runtime_id:
                raise ValueError(
                    "journal entry runtime_id does not "
                    "match analytics runtime"
                )

        closed = tuple(
            entry
            for entry in entries
            if entry.open_quantity == 0
        )

        open_entries = tuple(
            entry
            for entry in entries
            if entry.open_quantity > 0
        )

        wins = tuple(
            entry
            for entry in closed
            if entry.realized_pnl > 0
        )

        losses = tuple(
            entry
            for entry in closed
            if entry.realized_pnl < 0
        )

        breakeven = tuple(
            entry
            for entry in closed
            if entry.realized_pnl == 0
        )

        realized_pnl = sum(
            entry.realized_pnl
            for entry in entries
        )

        gross_profit = sum(
            entry.realized_pnl
            for entry in entries
            if entry.realized_pnl > 0
        )

        gross_loss = abs(
            sum(
                entry.realized_pnl
                for entry in entries
                if entry.realized_pnl < 0
            )
        )

        average_closed_position_pnl = (
            sum(
                entry.realized_pnl
                for entry in closed
            )
            / len(
                closed
            )
            if closed
            else 0.0
        )

        average_win = (
            sum(
                entry.realized_pnl
                for entry in wins
            )
            / len(
                wins
            )
            if wins
            else 0.0
        )

        average_loss = (
            sum(
                entry.realized_pnl
                for entry in losses
            )
            / len(
                losses
            )
            if losses
            else 0.0
        )

        largest_win = (
            max(
                entry.realized_pnl
                for entry in wins
            )
            if wins
            else 0.0
        )

        largest_loss = (
            min(
                entry.realized_pnl
                for entry in losses
            )
            if losses
            else 0.0
        )

        win_rate_percent = (
            (
                len(
                    wins
                )
                / len(
                    closed
                )
            )
            * 100.0
            if closed
            else 0.0
        )

        profit_factor = (
            gross_profit
            / gross_loss
            if gross_loss > 0
            else None
        )

        return TradeAnalyticsSummary(
            runtime_id=runtime_id,
            position_count=len(
                entries
            ),
            open_position_count=len(
                open_entries
            ),
            closed_position_count=len(
                closed
            ),
            winning_position_count=len(
                wins
            ),
            losing_position_count=len(
                losses
            ),
            breakeven_position_count=len(
                breakeven
            ),
            realized_pnl=realized_pnl,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            average_closed_position_pnl=(
                average_closed_position_pnl
            ),
            average_win=average_win,
            average_loss=average_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            win_rate_percent=win_rate_percent,
            profit_factor=profit_factor,
            total_original_quantity=sum(
                entry.original_quantity
                for entry in entries
            ),
            total_closed_quantity=sum(
                entry.closed_quantity
                for entry in entries
            ),
            total_exit_filled_quantity=sum(
                entry.exit_filled_quantity
                for entry in entries
            ),
            exit_persistence_mismatch_count=sum(
                1
                for entry in entries
                if not entry.exit_persistence_in_sync
            ),
            calculated_at=calculated_at,
        )


__all__ = [
    "TradeAnalyticsService",
]
