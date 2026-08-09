"""
Contract ranking policy for Phoenix Option Selection.

Ranks already-eligible option candidates deterministically.

This module assumes:
    - expiry has already been selected
    - option side has already been selected
    - delta eligibility has already been applied

No broker-specific logic belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import inf, isfinite

from src.option_selection.option_types import (
    OptionCandidate,
)


@dataclass(frozen=True, slots=True)
class ContractRankingConfig:
    """
    Ranking configuration for eligible option contracts.
    """

    preferred_delta: float = 0.60

    def __post_init__(self) -> None:
        if not isfinite(self.preferred_delta):
            raise ValueError(
                "preferred_delta must be a finite number"
            )

        if not 0 < self.preferred_delta <= 1:
            raise ValueError(
                "preferred_delta must be between 0 and 1"
            )


@dataclass(frozen=True, slots=True)
class RankedContract:
    """
    One ranked option candidate with diagnostic metrics.
    """

    candidate: OptionCandidate

    delta_distance: float
    spread: float | None
    strike_distance: float

    rank: int


class ContractRankingPolicy:
    """
    Ranks eligible Phoenix option contracts.

    Ranking priority:

        1. Closest absolute delta to preferred delta.
        2. Smaller bid-ask spread.
        3. Higher volume.
        4. Higher open interest.
        5. Strike closest to reference price.
        6. security_id for deterministic tie-break.

    Missing market-liquidity fields are treated conservatively.
    """

    def __init__(
        self,
        config: ContractRankingConfig | None = None,
    ) -> None:
        self._config = (
            config or ContractRankingConfig()
        )

    @property
    def config(self) -> ContractRankingConfig:
        return self._config

    def rank(
        self,
        candidates: tuple[
            OptionCandidate,
            ...
        ],
        reference_price: float,
    ) -> tuple[RankedContract, ...]:
        """
        Rank candidates from best to worst.
        """

        if not isfinite(reference_price):
            raise ValueError(
                "reference_price must be a finite number"
            )

        if reference_price <= 0:
            raise ValueError(
                "reference_price must be greater than zero"
            )

        ordered = sorted(
            candidates,
            key=lambda candidate: self._sort_key(
                candidate=candidate,
                reference_price=reference_price,
            ),
        )

        return tuple(
            RankedContract(
                candidate=candidate,
                delta_distance=self._delta_distance(
                    candidate
                ),
                spread=self._spread(
                    candidate
                ),
                strike_distance=abs(
                    candidate.contract.strike
                    - reference_price
                ),
                rank=index,
            )
            for index, candidate in enumerate(
                ordered,
                start=1,
            )
        )

    def best(
        self,
        candidates: tuple[
            OptionCandidate,
            ...
        ],
        reference_price: float,
    ) -> OptionCandidate | None:
        """
        Return highest-ranked candidate or None.
        """

        ranked = self.rank(
            candidates=candidates,
            reference_price=reference_price,
        )

        if not ranked:
            return None

        return ranked[0].candidate

    def _sort_key(
        self,
        candidate: OptionCandidate,
        reference_price: float,
    ) -> tuple[
        float,
        float,
        int,
        int,
        float,
        str,
    ]:
        """
        Produce deterministic ascending sort key.
        """

        delta_distance = self._delta_distance(
            candidate
        )

        spread = self._spread(candidate)

        spread_score = (
            spread
            if spread is not None
            else inf
        )

        volume = (
            candidate.quote.volume
            if candidate.quote.volume is not None
            else -1
        )

        open_interest = (
            candidate.quote.open_interest
            if candidate.quote.open_interest is not None
            else -1
        )

        strike_distance = abs(
            candidate.contract.strike
            - reference_price
        )

        return (
            delta_distance,
            spread_score,
            -volume,
            -open_interest,
            strike_distance,
            candidate.contract.security_id,
        )

    def _delta_distance(
        self,
        candidate: OptionCandidate,
    ) -> float:
        return abs(
            candidate.delta_magnitude
            - self._config.preferred_delta
        )

    @staticmethod
    def _spread(
        candidate: OptionCandidate,
    ) -> float | None:
        bid = candidate.quote.bid
        ask = candidate.quote.ask

        if bid is None or ask is None:
            return None

        return ask - bid