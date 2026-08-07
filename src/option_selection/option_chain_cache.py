"""
Thread-safe option-chain cache and freshness validation
for Phoenix Trading Platform.

Responsibilities:
    - Cache normalized OptionChainSnapshot objects.
    - Reuse sufficiently fresh option-chain data.
    - Validate snapshot age.
    - Validate candidate quote and Greeks age.
    - Support controlled cache invalidation.

No Dhan-specific API logic or option-ranking logic belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from threading import RLock

from src.option_selection.option_chain_provider import (
    OptionChainSnapshot,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionType,
)


@dataclass(frozen=True, slots=True)
class OptionChainCacheKey:
    """
    Unique cache identity for one option-chain selection scope.
    """

    underlying_symbol: str
    option_type: OptionType
    expiry: date | None

    def __post_init__(self) -> None:
        if not self.underlying_symbol.strip():
            raise ValueError(
                "underlying_symbol cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class OptionChainFreshnessConfig:
    """
    Freshness thresholds for option-chain data.
    """

    snapshot_max_age_seconds: float = 3.0
    quote_max_age_seconds: float = 3.0
    greeks_max_age_seconds: float = 3.0

    def __post_init__(self) -> None:
        values = {
            "snapshot_max_age_seconds": (
                self.snapshot_max_age_seconds
            ),
            "quote_max_age_seconds": (
                self.quote_max_age_seconds
            ),
            "greeks_max_age_seconds": (
                self.greeks_max_age_seconds
            ),
        }

        for name, value in values.items():
            if value <= 0:
                raise ValueError(
                    f"{name} must be greater than zero"
                )


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    """
    Result of validating one cached snapshot.
    """

    fresh: bool

    snapshot_fresh: bool
    quotes_fresh: bool
    greeks_fresh: bool

    stale_candidate_count: int = 0


class OptionChainFreshnessGuard:
    """
    Validates snapshot, quote, and Greeks freshness.
    """

    def __init__(
        self,
        config: OptionChainFreshnessConfig | None = None,
    ) -> None:
        self._config = (
            config or OptionChainFreshnessConfig()
        )

    @property
    def config(
        self,
    ) -> OptionChainFreshnessConfig:
        return self._config

    def evaluate(
        self,
        snapshot: OptionChainSnapshot,
        now: datetime,
    ) -> FreshnessResult:
        """
        Validate complete option-chain freshness.
        """

        snapshot_fresh = self._within_age(
            timestamp=snapshot.received_at,
            now=now,
            maximum_age_seconds=(
                self._config.snapshot_max_age_seconds
            ),
        )

        stale_quotes = 0
        stale_greeks = 0

        for candidate in snapshot.candidates:
            if not self._quote_is_fresh(
                candidate,
                now,
            ):
                stale_quotes += 1

            if not self._greeks_are_fresh(
                candidate,
                now,
            ):
                stale_greeks += 1

        quotes_fresh = stale_quotes == 0
        greeks_fresh = stale_greeks == 0

        stale_candidates = sum(
            1
            for candidate in snapshot.candidates
            if (
                not self._quote_is_fresh(
                    candidate,
                    now,
                )
                or not self._greeks_are_fresh(
                    candidate,
                    now,
                )
            )
        )

        return FreshnessResult(
            fresh=(
                snapshot_fresh
                and quotes_fresh
                and greeks_fresh
            ),
            snapshot_fresh=snapshot_fresh,
            quotes_fresh=quotes_fresh,
            greeks_fresh=greeks_fresh,
            stale_candidate_count=stale_candidates,
        )

    def is_fresh(
        self,
        snapshot: OptionChainSnapshot,
        now: datetime,
    ) -> bool:
        return self.evaluate(
            snapshot,
            now,
        ).fresh

    def filter_fresh_candidates(
        self,
        snapshot: OptionChainSnapshot,
        now: datetime,
    ) -> tuple[OptionCandidate, ...]:
        """
        Return only candidates whose quote and Greeks
        are both fresh.
        """

        return tuple(
            candidate
            for candidate in snapshot.candidates
            if (
                self._quote_is_fresh(
                    candidate,
                    now,
                )
                and self._greeks_are_fresh(
                    candidate,
                    now,
                )
            )
        )

    def _quote_is_fresh(
        self,
        candidate: OptionCandidate,
        now: datetime,
    ) -> bool:
        return self._within_age(
            timestamp=(
                candidate.quote.received_at
            ),
            now=now,
            maximum_age_seconds=(
                self._config.quote_max_age_seconds
            ),
        )

    def _greeks_are_fresh(
        self,
        candidate: OptionCandidate,
        now: datetime,
    ) -> bool:
        calculated_at = (
            candidate.greeks.calculated_at
        )

        if calculated_at is None:
            return False

        return self._within_age(
            timestamp=calculated_at,
            now=now,
            maximum_age_seconds=(
                self._config.greeks_max_age_seconds
            ),
        )

    @staticmethod
    def _within_age(
        timestamp: datetime,
        now: datetime,
        maximum_age_seconds: float,
    ) -> bool:
        """
        Timestamp must not be from the future and
        must be within maximum permitted age.
        """

        age = now - timestamp

        if age < timedelta(0):
            return False

        return (
            age
            <= timedelta(
                seconds=maximum_age_seconds
            )
        )


class OptionChainCache:
    """
    Thread-safe in-memory option-chain cache.

    Cached data is returned only when the supplied
    freshness guard considers it usable.
    """

    def __init__(
        self,
        freshness_guard: OptionChainFreshnessGuard,
    ) -> None:
        self._freshness_guard = (
            freshness_guard
        )

        self._snapshots: dict[
            OptionChainCacheKey,
            OptionChainSnapshot,
        ] = {}

        self._lock = RLock()

    def put(
        self,
        key: OptionChainCacheKey,
        snapshot: OptionChainSnapshot,
    ) -> None:
        """
        Store or replace one option-chain snapshot.
        """

        with self._lock:
            self._snapshots[key] = snapshot

    def get(
        self,
        key: OptionChainCacheKey,
    ) -> OptionChainSnapshot | None:
        """
        Return cached snapshot regardless of freshness.
        """

        with self._lock:
            return self._snapshots.get(
                key
            )

    def get_fresh(
        self,
        key: OptionChainCacheKey,
        now: datetime,
    ) -> OptionChainSnapshot | None:
        """
        Return cached snapshot only when fresh.
        """

        with self._lock:
            snapshot = self._snapshots.get(
                key
            )

            if snapshot is None:
                return None

            if not self._freshness_guard.is_fresh(
                snapshot=snapshot,
                now=now,
            ):
                return None

            return snapshot

    def remove(
        self,
        key: OptionChainCacheKey,
    ) -> bool:
        """
        Remove one cached snapshot.
        """

        with self._lock:
            return (
                self._snapshots.pop(
                    key,
                    None,
                )
                is not None
            )

    def clear(self) -> int:
        """
        Clear complete cache.

        Returns number of snapshots removed.
        """

        with self._lock:
            removed = len(
                self._snapshots
            )

            self._snapshots.clear()

            return removed

    def count(self) -> int:
        with self._lock:
            return len(
                self._snapshots
            )