"""
Phoenix Option Selection Service.

Orchestrates the M04 TradingSignal -> M05 SelectedOption flow.

Responsibilities:
    - Validate supported underlying.
    - Map SignalDirection to OptionType.
    - Build OptionChainRequest.
    - Obtain normalized snapshot from OptionChainProvider.
    - Invoke OptionSelector.
    - Return OptionSelectionResult.

No broker-specific parsing or order execution belongs here.
"""

from __future__ import annotations

from datetime import date, datetime

from src.option_selection.option_chain_provider import (
    OptionChainProvider,
    OptionChainRequest,
)
from src.option_selection.option_selector import (
    OptionSelectionRequest,
    OptionSelector,
)
from src.option_selection.option_types import (
    OptionSelectionResult,
    OptionSelectionStatus,
    OptionType,
)
from src.signals.signal_types import (
    SignalDirection,
    TradingSignal,
)


class OptionSelectionService:
    """
    Main M05 option-selection orchestrator.
    """

    def __init__(
        self,
        provider: OptionChainProvider,
        selector: OptionSelector,
        supported_underlying: str = "NIFTY 50",
    ) -> None:
        normalized_underlying = supported_underlying.strip()

        if not normalized_underlying:
            raise ValueError(
                "supported_underlying cannot be empty"
            )

        self._provider = provider
        self._selector = selector
        self._supported_underlying = normalized_underlying

    @property
    def provider(self) -> OptionChainProvider:
        return self._provider

    @property
    def supported_underlying(self) -> str:
        return self._supported_underlying

    def select_for_signal(
        self,
        signal: TradingSignal,
        requested_at: datetime,
        requested_expiry: date | None = None,
    ) -> OptionSelectionResult:
        """
        Select one option contract for a TradingSignal.
        """

        if (
            signal.underlying_symbol
            != self._supported_underlying
        ):
            return OptionSelectionResult(
                status=OptionSelectionStatus.INVALID_REQUEST,
                message=(
                    "Unsupported underlying: "
                    f"{signal.underlying_symbol}"
                ),
            )

        option_type = self._map_direction(
            signal.direction
        )

        provider_request = OptionChainRequest(
            underlying_symbol=signal.underlying_symbol,
            option_type=option_type,
            reference_price=signal.underlying_price,
            requested_at=requested_at,
            expiry=requested_expiry,
        )

        try:
            snapshot = self._provider.get_option_chain(
                provider_request
            )

        except Exception as exc:
            return OptionSelectionResult(
                status=OptionSelectionStatus.PROVIDER_ERROR,
                message=(
                    "Option chain provider failed: "
                    f"{exc}"
                ),
            )

        selector_request = OptionSelectionRequest(
            option_type=option_type,
            trading_date=signal.trading_date,
            reference_price=signal.underlying_price,
            selected_at=requested_at,
            requested_expiry=requested_expiry,
        )

        return self._selector.select(
            snapshot=snapshot,
            request=selector_request,
        )

    @staticmethod
    def _map_direction(
        direction: SignalDirection,
    ) -> OptionType:
        """
        Map M04 signal direction to M05 option type.
        """

        mapping = {
            SignalDirection.CALL: OptionType.CALL,
            SignalDirection.PUT: OptionType.PUT,
        }

        return mapping[direction]