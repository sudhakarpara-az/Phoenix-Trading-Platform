"""
Broker-independent option-chain provider interface.

Defines the contract used by Phoenix Option Selection
to obtain normalized option-chain candidates.

Concrete broker adapters, such as Dhan, must implement
this interface without leaking broker-specific response
structures into the selection engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime

from src.option_selection.option_types import (
    OptionCandidate,
    OptionType,
)


@dataclass(frozen=True, slots=True)
class OptionChainRequest:
    """
    Request for normalized option-chain data.
    """

    underlying_symbol: str
    option_type: OptionType

    reference_price: float

    requested_at: datetime

    expiry: date | None = None

    def __post_init__(self) -> None:
        if not self.underlying_symbol.strip():
            raise ValueError(
                "underlying_symbol cannot be empty"
            )

        if self.reference_price <= 0:
            raise ValueError(
                "reference_price must be greater than zero"
            )


@dataclass(frozen=True, slots=True)
class OptionChainSnapshot:
    """
    Normalized option-chain snapshot returned by a provider.

    The snapshot is immutable so downstream filtering and
    ranking operate on a stable view of the option chain.
    """

    underlying_symbol: str

    reference_price: float

    candidates: tuple[OptionCandidate, ...]

    received_at: datetime

    provider_name: str

    def __post_init__(self) -> None:
        if not self.underlying_symbol.strip():
            raise ValueError(
                "underlying_symbol cannot be empty"
            )

        if self.reference_price <= 0:
            raise ValueError(
                "reference_price must be greater than zero"
            )

        if not self.provider_name.strip():
            raise ValueError(
                "provider_name cannot be empty"
            )

    def count(self) -> int:
        """
        Return number of normalized option candidates.
        """

        return len(self.candidates)

    def is_empty(self) -> bool:
        """
        Return True when the provider returned no contracts.
        """

        return not self.candidates

    def by_option_type(
        self,
        option_type: OptionType,
    ) -> tuple[OptionCandidate, ...]:
        """
        Return candidates matching the requested option side.
        """

        return tuple(
            candidate
            for candidate in self.candidates
            if (
                candidate.contract.option_type
                is option_type
            )
        )

    def by_expiry(
        self,
        expiry: date,
    ) -> tuple[OptionCandidate, ...]:
        """
        Return candidates matching one expiry date.
        """

        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.contract.expiry == expiry
        )


class OptionChainProvider(ABC):
    """
    Abstract option-chain provider.

    Phoenix selection logic must depend on this interface,
    not directly on Dhan or another broker SDK.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Return stable provider identifier.
        """

        raise NotImplementedError

    @abstractmethod
    def get_option_chain(
        self,
        request: OptionChainRequest,
    ) -> OptionChainSnapshot:
        """
        Fetch and normalize an option-chain snapshot.
        """

        raise NotImplementedError