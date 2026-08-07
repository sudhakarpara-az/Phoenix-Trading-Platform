"""
Expiry selection policy for Phoenix Option Selection.

Selects one valid option expiry from normalized
OptionCandidate data.

No broker-specific logic belongs in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.option_selection.option_types import (
    OptionCandidate,
)


@dataclass(frozen=True, slots=True)
class ExpirySelectionResult:
    """
    Result of expiry selection.
    """

    expiry: date | None
    candidates: tuple[OptionCandidate, ...]

    @property
    def selected(self) -> bool:
        return self.expiry is not None

    @property
    def count(self) -> int:
        return len(self.candidates)


class ExpirySelectionPolicy:
    """
    Selects the correct option expiry.

    Rules:
        - Expired contracts are ignored.
        - Explicit requested expiry takes precedence.
        - Otherwise nearest valid expiry is selected.
        - All returned candidates belong to one expiry.
    """

    def select(
        self,
        candidates: tuple[OptionCandidate, ...],
        trading_date: date,
        requested_expiry: date | None = None,
    ) -> ExpirySelectionResult:
        """
        Select one valid expiry and return matching candidates.
        """

        valid_candidates = tuple(
            candidate
            for candidate in candidates
            if candidate.contract.expiry >= trading_date
        )

        if not valid_candidates:
            return ExpirySelectionResult(
                expiry=None,
                candidates=(),
            )

        if requested_expiry is not None:
            requested_candidates = tuple(
                candidate
                for candidate in valid_candidates
                if (
                    candidate.contract.expiry
                    == requested_expiry
                )
            )

            if not requested_candidates:
                return ExpirySelectionResult(
                    expiry=None,
                    candidates=(),
                )

            return ExpirySelectionResult(
                expiry=requested_expiry,
                candidates=requested_candidates,
            )

        nearest_expiry = min(
            candidate.contract.expiry
            for candidate in valid_candidates
        )

        selected_candidates = tuple(
            candidate
            for candidate in valid_candidates
            if candidate.contract.expiry == nearest_expiry
        )

        return ExpirySelectionResult(
            expiry=nearest_expiry,
            candidates=selected_candidates,
        )