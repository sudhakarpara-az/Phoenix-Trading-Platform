"""
Session Manager

Responsible for managing strategy trading sessions.
"""

from __future__ import annotations

from datetime import datetime, time


class SessionManager:
    """
    Controls the trading session timings.
    """

    ENTRY_START_TIME = time(9, 20)
    FORCE_EXIT_TIME = time(15, 15)

    def can_trade(self, current_time: datetime | None = None) -> bool:
        """
        Returns True if new entries are allowed.
        """

        if current_time is None:
            current_time = datetime.now()

        now = current_time.time()

        return self.ENTRY_START_TIME <= now < self.FORCE_EXIT_TIME

    def should_force_exit(self, current_time: datetime | None = None) -> bool:
        """
        Returns True if all positions should be exited.
        """

        if current_time is None:
            current_time = datetime.now()

        return current_time.time() >= self.FORCE_EXIT_TIME

    def is_before_market(self, current_time: datetime | None = None) -> bool:
        """
        Returns True if market entry time has not started.
        """

        if current_time is None:
            current_time = datetime.now()

        return current_time.time() < self.ENTRY_START_TIME

    def is_market_closed(self, current_time: datetime | None = None) -> bool:
        """
        Returns True if trading session has ended.
        """

        if current_time is None:
            current_time = datetime.now()

        return current_time.time() >= self.FORCE_EXIT_TIME