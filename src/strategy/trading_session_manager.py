"""
Daily trading-session lifecycle management
for the KS Phoenix strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from threading import RLock

from src.strategy.strategy_types import (
    StrategySessionState,
)


@dataclass(frozen=True, slots=True)
class TradingSessionConfig:
    """
    Time configuration for the KS Phoenix trading session.

    reference_candle_end controls only reference-candle
    completion.

    monitoring_start is intentionally separate so reference
    calculations may complete before entry monitoring begins.
    """

    market_open: time = time(9, 15)
    reference_candle_end: time = time(9, 16)
    monitoring_start: time = time(9, 20)
    force_exit: time = time(15, 15)

    def __post_init__(self) -> None:
        if (
            self.reference_candle_end
            <= self.market_open
        ):
            raise ValueError(
                "reference_candle_end must be after market_open"
            )

        if (
            self.monitoring_start
            < self.reference_candle_end
        ):
            raise ValueError(
                "monitoring_start cannot be before "
                "reference_candle_end"
            )

        if self.force_exit <= self.monitoring_start:
            raise ValueError(
                "force_exit must be after monitoring_start"
            )


class TradingSessionManager:
    """
    Controls the daily lifecycle of KS Phoenix.

    Reference-candle formation and entry-monitoring activation
    are separate lifecycle boundaries.

    This class is broker-independent and contains no
    order, option-selection, or market-feed logic.
    """

    def __init__(
        self,
        config: TradingSessionConfig | None = None,
    ) -> None:
        self._config = (
            config
            or TradingSessionConfig()
        )

        self._state = (
            StrategySessionState.WAITING_FOR_MARKET
        )

        self._trading_date: date | None = None
        self._levels_ready = False

        self._last_update_at: datetime | None = None

        self._lock = RLock()

    @property
    def config(self) -> TradingSessionConfig:
        return self._config

    @property
    def trading_date(self) -> date | None:
        with self._lock:
            return self._trading_date

    def state(self) -> StrategySessionState:
        with self._lock:
            return self._state

    def mark_levels_ready(self) -> None:
        """
        Mark the day's KS calculations as complete.

        Completing KS calculations does not itself permit
        monitoring before monitoring_start.
        """

        with self._lock:
            self._levels_ready = True

            if self._last_update_at is None:
                return

            current_time = (
                self._last_update_at.time()
            )

            if (
                self._state
                is StrategySessionState.LEVELS_READY
                and current_time
                >= self._config.monitoring_start
                and current_time
                < self._config.force_exit
            ):
                self._state = (
                    StrategySessionState.MONITORING
                )

    def reset_for_day(
        self,
        trading_date: date,
    ) -> None:
        """
        Reset all session state for a new trading day.
        """

        with self._lock:
            self._trading_date = trading_date
            self._levels_ready = False
            self._last_update_at = None

            self._state = (
                StrategySessionState.WAITING_FOR_MARKET
            )

    def update(
        self,
        now: datetime,
    ) -> StrategySessionState:
        """
        Evaluate the correct strategy state for the supplied time.
        """

        with self._lock:
            self._ensure_trading_date(
                now.date()
            )

            self._last_update_at = now

            current_time = now.time()

            if current_time >= self._config.force_exit:
                self._state = (
                    StrategySessionState.CLOSED
                )

                return self._state

            if current_time < self._config.market_open:
                self._state = (
                    StrategySessionState.WAITING_FOR_MARKET
                )

                return self._state

            if (
                self._config.market_open
                <= current_time
                < self._config.reference_candle_end
            ):
                self._state = (
                    StrategySessionState.BUILDING_REFERENCE_CANDLE
                )

                return self._state

            if (
                current_time
                < self._config.monitoring_start
            ):
                self._state = (
                    StrategySessionState.LEVELS_READY
                )

                return self._state

            if not self._levels_ready:
                self._state = (
                    StrategySessionState.LEVELS_READY
                )

                return self._state

            self._state = (
                StrategySessionState.MONITORING
            )

            return self._state

    def is_reference_candle_window(
        self,
        now: datetime,
    ) -> bool:
        """
        Return True during the configured reference-candle window.
        """

        current_time = now.time()

        return (
            self._config.market_open
            <= current_time
            < self._config.reference_candle_end
        )

    def can_monitor_levels(
        self,
        now: datetime,
    ) -> bool:
        """
        Return True only when KS levels are ready and
        monitoring_start has been reached.
        """

        state = self.update(now)

        return (
            state
            is StrategySessionState.MONITORING
        )

    def is_force_exit_time(
        self,
        now: datetime,
    ) -> bool:
        """
        Return True once the force-exit time has been reached.
        """

        return (
            now.time()
            >= self._config.force_exit
        )

    def _ensure_trading_date(
        self,
        current_date: date,
    ) -> None:
        if self._trading_date != current_date:
            self._trading_date = current_date
            self._levels_ready = False
            self._last_update_at = None