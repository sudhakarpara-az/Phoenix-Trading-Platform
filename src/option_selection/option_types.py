"""
Phoenix Option Selection domain models.

These models represent broker-independent NIFTY option-chain
data and the final option-selection result.

No Dhan-specific parsing, selection policy, ranking,
or order-execution logic belongs in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite


class OptionType(str, Enum):
    """
    Supported option contract types.

    Phoenix Phase 1 supports option buying only,
    on both CALL and PUT sides.
    """

    CALL = "CALL"
    PUT = "PUT"


class OptionSelectionStatus(str, Enum):
    """
    Outcome of an option-selection request.
    """

    SELECTED = "SELECTED"
    NO_CONTRACTS = "NO_CONTRACTS"
    NO_VALID_EXPIRY = "NO_VALID_EXPIRY"
    NO_DELTA_MATCH = "NO_DELTA_MATCH"
    NO_VALID_QUOTE = "NO_VALID_QUOTE"
    STALE_DATA = "STALE_DATA"
    INVALID_REQUEST = "INVALID_REQUEST"
    PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass(frozen=True, slots=True)
class OptionGreeks:
    """
    Greeks associated with one option contract.

    Delta is required for the Phoenix selection strategy.

    CALL delta is normally positive.
    PUT delta is normally negative.

    M05 filtering will compare abs(delta) against
    the configured Phoenix delta range.
    """

    delta: float

    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None

    implied_volatility: float | None = None

    calculated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.delta):
            raise ValueError(
                "delta must be a finite number"
            )

        if not -1.0 <= self.delta <= 1.0:
            raise ValueError(
                "delta must be between -1 and 1"
            )

        optional_values = {
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "implied_volatility": self.implied_volatility,
        }

        for name, value in optional_values.items():
            if value is not None and not isfinite(value):
                raise ValueError(
                    f"{name} must be a finite number"
                )

        if (
            self.implied_volatility is not None
            and self.implied_volatility < 0
        ):
            raise ValueError(
                "implied_volatility cannot be negative"
            )

    @property
    def delta_magnitude(self) -> float:
        """
        Return absolute delta used by Phoenix selection.

        Examples:
            CALL +0.64 -> 0.64
            PUT  -0.64 -> 0.64
        """

        return abs(self.delta)


@dataclass(frozen=True, slots=True)
class OptionQuote:
    """
    Latest market quote for one option contract.
    """

    ltp: float
    received_at: datetime

    bid: float | None = None
    ask: float | None = None

    volume: int | None = None
    open_interest: int | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.ltp):
            raise ValueError(
                "ltp must be a finite number"
            )

        if self.ltp <= 0:
            raise ValueError(
                "ltp must be greater than zero"
            )

        if self.bid is not None:
            if not isfinite(self.bid):
                raise ValueError(
                    "bid must be a finite number"
                )

            if self.bid < 0:
                raise ValueError(
                    "bid cannot be negative"
                )

        if self.ask is not None:
            if not isfinite(self.ask):
                raise ValueError(
                    "ask must be a finite number"
                )

            if self.ask < 0:
                raise ValueError(
                    "ask cannot be negative"
                )

        if (
            self.bid is not None
            and self.ask is not None
            and self.bid > self.ask
        ):
            raise ValueError(
                "bid cannot be greater than ask"
            )

        if self.volume is not None and self.volume < 0:
            raise ValueError(
                "volume cannot be negative"
            )

        if (
            self.open_interest is not None
            and self.open_interest < 0
        ):
            raise ValueError(
                "open_interest cannot be negative"
            )


@dataclass(frozen=True, slots=True)
class OptionContract:
    """
    Broker-independent NIFTY option contract.

    security_id is the broker/instrument-master identifier,
    but the model itself remains independent of Dhan APIs.
    """

    underlying_symbol: str

    symbol: str
    security_id: str

    option_type: OptionType

    strike: float
    expiry: date

    lot_size: int

    def __post_init__(self) -> None:
        if not self.underlying_symbol.strip():
            raise ValueError(
                "underlying_symbol cannot be empty"
            )

        if not self.symbol.strip():
            raise ValueError(
                "symbol cannot be empty"
            )

        if not self.security_id.strip():
            raise ValueError(
                "security_id cannot be empty"
            )

        if not isfinite(self.strike):
            raise ValueError(
                "strike must be a finite number"
            )

        if self.strike <= 0:
            raise ValueError(
                "strike must be greater than zero"
            )

        if self.lot_size <= 0:
            raise ValueError(
                "lot_size must be greater than zero"
            )


@dataclass(frozen=True, slots=True)
class OptionCandidate:
    """
    Complete option-selection candidate.

    Combines:
        contract identity
        latest quote
        Greeks
    """

    contract: OptionContract
    quote: OptionQuote
    greeks: OptionGreeks

    @property
    def delta(self) -> float:
        return self.greeks.delta

    @property
    def delta_magnitude(self) -> float:
        return self.greeks.delta_magnitude

    @property
    def ltp(self) -> float:
        return self.quote.ltp


@dataclass(frozen=True, slots=True)
class SelectedOption:
    """
    Final output from M05 option selection.

    This is the contract that will later be handed
    to M06 execution.

    It deliberately contains no:
        limit price
        stop-loss
        target
        broker order ID
        fill price
    """

    candidate: OptionCandidate

    selected_at: datetime

    selection_delta_target: float

    @property
    def contract(self) -> OptionContract:
        return self.candidate.contract

    @property
    def symbol(self) -> str:
        return self.candidate.contract.symbol

    @property
    def security_id(self) -> str:
        return self.candidate.contract.security_id

    @property
    def option_type(self) -> OptionType:
        return self.candidate.contract.option_type

    @property
    def strike(self) -> float:
        return self.candidate.contract.strike

    @property
    def expiry(self) -> date:
        return self.candidate.contract.expiry

    @property
    def lot_size(self) -> int:
        return self.candidate.contract.lot_size

    @property
    def delta(self) -> float:
        return self.candidate.delta

    @property
    def delta_magnitude(self) -> float:
        return self.candidate.delta_magnitude

    @property
    def ltp(self) -> float:
        return self.candidate.ltp

    def __post_init__(self) -> None:
        if not isfinite(self.selection_delta_target):
            raise ValueError(
                "selection_delta_target must be finite"
            )

        if not 0 < self.selection_delta_target <= 1:
            raise ValueError(
                "selection_delta_target must be between 0 and 1"
            )


@dataclass(frozen=True, slots=True)
class OptionSelectionResult:
    """
    Result returned by the M05 selection subsystem.
    """

    status: OptionSelectionStatus

    selected_option: SelectedOption | None = None

    message: str | None = None

    def __post_init__(self) -> None:
        if (
            self.status is OptionSelectionStatus.SELECTED
            and self.selected_option is None
        ):
            raise ValueError(
                "SELECTED result must contain selected_option"
            )

        if (
            self.status is not OptionSelectionStatus.SELECTED
            and self.selected_option is not None
        ):
            raise ValueError(
                "failed selection result cannot contain selected_option"
            )

        if self.message is not None and not self.message.strip():
            raise ValueError(
                "message cannot be empty"
            )