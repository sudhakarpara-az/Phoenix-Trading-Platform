"""
Delta eligibility filtering for Phoenix Option Selection.

Filters normalized OptionCandidate objects using the
configured absolute-delta range.

Current Phoenix rule:

    0.59 <= abs(delta) <= 0.69

The preferred target delta is retained in configuration
for downstream ranking, but this module does not rank contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from src.option_selection.option_types import (
    OptionCandidate,
)


@dataclass(frozen=True, slots=True)
class DeltaFilterConfig:
    """
    Phoenix delta-selection configuration.

    minimum_delta and maximum_delta apply to absolute
    delta magnitude for both CALL and PUT contracts.
    """

    minimum_delta: float = 0.59
    maximum_delta: float = 0.69
    preferred_delta: float = 0.60

    def __post_init__(self) -> None:
        values = {
            "minimum_delta": self.minimum_delta,
            "maximum_delta": self.maximum_delta,
            "preferred_delta": self.preferred_delta,
        }

        for name, value in values.items():
            if not isfinite(value):
                raise ValueError(
                    f"{name} must be a finite number"
                )

            if not 0 < value <= 1:
                raise ValueError(
                    f"{name} must be between 0 and 1"
                )

        if self.minimum_delta > self.maximum_delta:
            raise ValueError(
                "minimum_delta cannot be greater than maximum_delta"
            )

        if not (
            self.minimum_delta
            <= self.preferred_delta
            <= self.maximum_delta
        ):
            raise ValueError(
                "preferred_delta must be within configured delta range"
            )


@dataclass(frozen=True, slots=True)
class DeltaFilterResult:
    """
    Result of applying the Phoenix delta filter.
    """

    eligible: tuple[OptionCandidate, ...]

    total_candidates: int

    rejected_candidates: int

    @property
    def count(self) -> int:
        return len(self.eligible)

    @property
    def has_matches(self) -> bool:
        return bool(self.eligible)


class DeltaEligibilityFilter:
    """
    Filters option candidates using absolute delta magnitude.

    Examples:

        CALL +0.58 -> rejected
        CALL +0.59 -> eligible
        CALL +0.64 -> eligible
        CALL +0.69 -> eligible
        CALL +0.70 -> rejected

        PUT -0.58 -> rejected
        PUT -0.59 -> eligible
        PUT -0.64 -> eligible
        PUT -0.69 -> eligible
        PUT -0.70 -> rejected
    """

    def __init__(
        self,
        config: DeltaFilterConfig | None = None,
    ) -> None:
        self._config = (
            config or DeltaFilterConfig()
        )

    @property
    def config(self) -> DeltaFilterConfig:
        return self._config

    def is_eligible(
        self,
        candidate: OptionCandidate,
    ) -> bool:
        """
        Return True when candidate delta magnitude falls
        inside the inclusive Phoenix delta range.
        """

        magnitude = candidate.delta_magnitude

        return (
            self._config.minimum_delta
            <= magnitude
            <= self._config.maximum_delta
        )

    def filter(
        self,
        candidates: tuple[
            OptionCandidate,
            ...
        ],
    ) -> DeltaFilterResult:
        """
        Return all candidates satisfying the configured
        absolute-delta range.

        Input ordering is preserved.
        """

        eligible = tuple(
            candidate
            for candidate in candidates
            if self.is_eligible(candidate)
        )

        total = len(candidates)

        return DeltaFilterResult(
            eligible=eligible,
            total_candidates=total,
            rejected_candidates=(
                total - len(eligible)
            ),
        )