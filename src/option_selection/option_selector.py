"""
Phoenix Option Selector.

Combines option-side filtering, expiry selection,
delta eligibility filtering, and contract ranking
to produce one SelectedOption.

No broker API calls or order execution belong here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.option_selection.contract_ranker import (
    ContractRankingPolicy,
)
from src.option_selection.delta_filter import (
    DeltaEligibilityFilter,
)
from src.option_selection.expiry_selector import (
    ExpirySelectionPolicy,
)
from src.option_selection.option_chain_provider import (
    OptionChainSnapshot,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionSelectionResult,
    OptionSelectionStatus,
    OptionType,
    SelectedOption,
)


@dataclass(frozen=True, slots=True)
class OptionSelectionRequest:
    """
    Input required by the broker-independent OptionSelector.
    """

    option_type: OptionType

    trading_date: date
    reference_price: float

    selected_at: datetime

    requested_expiry: date | None = None

    def __post_init__(self) -> None:
        if self.reference_price <= 0:
            raise ValueError(
                "reference_price must be greater than zero"
            )


class OptionSelector:
    """
    Selects one Phoenix option contract from
    a normalized OptionChainSnapshot.

    Processing order:

        1. Validate underlying snapshot.
        2. Filter CALL or PUT side.
        3. Select expiry.
        4. Apply 0.59-0.69 delta eligibility.
        5. Rank eligible contracts around preferred delta.
        6. Return SelectedOption.
    """

    def __init__(
        self,
        expiry_policy: ExpirySelectionPolicy,
        delta_filter: DeltaEligibilityFilter,
        contract_ranker: ContractRankingPolicy,
    ) -> None:
        self._expiry_policy = expiry_policy
        self._delta_filter = delta_filter
        self._contract_ranker = contract_ranker

    def select(
        self,
        snapshot: OptionChainSnapshot,
        request: OptionSelectionRequest,
    ) -> OptionSelectionResult:
        """
        Select one best option contract.
        """

        if snapshot.is_empty():
            return OptionSelectionResult(
                status=OptionSelectionStatus.NO_CONTRACTS,
                message="Option chain contains no candidates",
            )

        if snapshot.reference_price <= 0:
            return OptionSelectionResult(
                status=OptionSelectionStatus.INVALID_REQUEST,
                message="Snapshot reference price is invalid",
            )

        side_candidates = snapshot.by_option_type(
            request.option_type
        )

        if not side_candidates:
            return OptionSelectionResult(
                status=OptionSelectionStatus.NO_CONTRACTS,
                message=(
                    f"No {request.option_type.value} "
                    f"contracts available"
                ),
            )

        expiry_result = self._expiry_policy.select(
            candidates=side_candidates,
            trading_date=request.trading_date,
            requested_expiry=request.requested_expiry,
        )

        if not expiry_result.selected:
            return OptionSelectionResult(
                status=OptionSelectionStatus.NO_VALID_EXPIRY,
                message="No valid expiry available",
            )

        delta_result = self._delta_filter.filter(
            expiry_result.candidates
        )

        if not delta_result.has_matches:
            return OptionSelectionResult(
                status=OptionSelectionStatus.NO_DELTA_MATCH,
                message=(
                    "No option matched configured "
                    "delta eligibility range"
                ),
            )

        best_candidate = self._contract_ranker.best(
            candidates=delta_result.eligible,
            reference_price=request.reference_price,
        )

        if best_candidate is None:
            return OptionSelectionResult(
                status=OptionSelectionStatus.NO_VALID_QUOTE,
                message="No rankable option candidate available",
            )

        selected = SelectedOption(
            candidate=best_candidate,
            selected_at=request.selected_at,
            selection_delta_target=(
                self._contract_ranker.config.preferred_delta
            ),
        )

        return OptionSelectionResult(
            status=OptionSelectionStatus.SELECTED,
            selected_option=selected,
        )