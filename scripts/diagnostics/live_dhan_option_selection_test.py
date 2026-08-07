"""
M05-T11 — Live Dhan Option Selection Diagnostic

READ-ONLY TEST.

This script:

    1. Authenticates using the existing Phoenix DhanBroker.
    2. Resolves the nearest valid NIFTY option expiry.
    3. Fetches the real Dhan NIFTY option chain.
    4. Runs the Phoenix M05 selection pipeline.
    5. Selects CALL and PUT contracts using:
           0.59 <= abs(delta) <= 0.69
           preferred delta = 0.64

This script DOES NOT:
    - place an order
    - modify an order
    - cancel an order
    - create a position
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime
from pathlib import Path


# ---------------------------------------------------------
# Ensure project root is importable when running directly
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


from src.broker.dhan_broker import DhanBroker

from src.option_selection.contract_ranker import (
    ContractRankingPolicy,
)
from src.option_selection.delta_filter import (
    DeltaEligibilityFilter,
)
from src.option_selection.dhan_option_chain_adapter import (
    DhanOptionChainAdapter,
)
from src.option_selection.expiry_selector import (
    ExpirySelectionPolicy,
)
from src.option_selection.option_selector import (
    OptionSelector,
)
from src.option_selection.option_types import (
    OptionSelectionStatus,
    OptionType,
)
from src.option_selection.selection_service import (
    OptionSelectionService,
)

from src.signals.signal_types import (
    SignalDirection,
    SignalId,
    SignalReason,
    SignalState,
    TradingSignal,
)

from src.strategy.strategy_types import (
    EntryLevel,
)


NIFTY_SYMBOL = "NIFTY 50"
NIFTY_SECURITY_ID = "13"

DELTA_MIN = 0.59
DELTA_MAX = 0.69
PREFERRED_DELTA = 0.64

# Respect Dhan Option Chain request cadence.
REQUEST_DELAY_SECONDS = 3.2


def get_dhan_client():
    """
    Use the Phoenix broker abstraction instead of
    constructing another Dhan client manually.
    """

    broker = DhanBroker()

    if hasattr(
        broker,
        "get_client",
    ):
        return broker.get_client()

    if hasattr(
        broker,
        "get_context",
    ):
        return broker.get_context()

    raise RuntimeError(
        "DhanBroker exposes neither get_client() nor get_context()"
    )


def get_expiry_list(
    dhan_client,
) -> list[str]:
    """
    Fetch and normalize the Dhan expiry-list response.

    Supports:
        1. Raw REST/API response:
           {
               "status": "success",
               "data": ["2026-08-13", ...]
           }

        2. SDK responses where data may be nested:
           {
               "status": "success",
               "data": {
                   "data": [...]
               }
           }

        3. SDK methods returning the expiry list directly.
    """

    if hasattr(
        dhan_client,
        "get_expiry_list",
    ):
        response = dhan_client.get_expiry_list(
            underlying_security_id=13,
            underlying_type="INDEX",
        )

    elif hasattr(
        dhan_client,
        "expiry_list",
    ):
        response = dhan_client.expiry_list(
            13,
            "IDX_I",
        )

    else:
        raise RuntimeError(
            "Installed Dhan client does not expose "
            "an expiry-list API"
        )

    # ---------------------------------------------------------
    # Diagnostic output
    # ---------------------------------------------------------

    print()
    print("RAW DHAN EXPIRY RESPONSE:")
    print(response)
    print()

    # ---------------------------------------------------------
    # Case 1:
    # SDK returns list directly
    # ---------------------------------------------------------

    if isinstance(response, list):
        return [
            str(value)
            for value in response
        ]

    # ---------------------------------------------------------
    # Remaining cases require dictionary response
    # ---------------------------------------------------------

    if not isinstance(
        response,
        dict,
    ):
        raise RuntimeError(
            "Unexpected Dhan expiry response type: "
            f"{type(response).__name__}: "
            f"{response!r}"
        )

    status = response.get(
        "status"
    )

    if (
        status is not None
        and str(status).lower()
        != "success"
    ):
        raise RuntimeError(
            "Dhan expiry request failed: "
            f"{response}"
        )

    data = response.get(
        "data"
    )

    # ---------------------------------------------------------
    # Case 2:
    # Normal Dhan REST response
    #
    # {
    #     "status": "success",
    #     "data": [...]
    # }
    # ---------------------------------------------------------

    if isinstance(
        data,
        list,
    ):
        return [
            str(value)
            for value in data
        ]

    # ---------------------------------------------------------
    # Case 3:
    # Nested SDK response
    #
    # {
    #     "status": "success",
    #     "data": {
    #         "data": [...]
    #     }
    # }
    # ---------------------------------------------------------

    if isinstance(
        data,
        dict,
    ):
        nested_data = data.get(
            "data"
        )

        if isinstance(
            nested_data,
            list,
        ):
            return [
                str(value)
                for value in nested_data
            ]

        # Some wrappers may expose expiries using a named key.
        for key in (
            "expiries",
            "expiry_list",
            "expiryList",
            "expiry_dates",
        ):
            possible_list = data.get(
                key
            )

            if isinstance(
                possible_list,
                list,
            ):
                return [
                    str(value)
                    for value in possible_list
                ]

    # ---------------------------------------------------------
    # Case 4:
    # Top-level alternative list keys
    # ---------------------------------------------------------

    for key in (
        "expiries",
        "expiry_list",
        "expiryList",
        "expiry_dates",
    ):
        possible_list = response.get(
            key
        )

        if isinstance(
            possible_list,
            list,
        ):
            return [
                str(value)
                for value in possible_list
            ]

    raise RuntimeError(
        "Dhan expiry response does not contain "
        "a recognizable expiry list. "
        f"Response: {response!r}"
    )

def nearest_valid_expiry(
    raw_expiries: list[str],
    trading_date: date,
) -> date:
    expiries: list[date] = []

    for raw_value in raw_expiries:
        try:
            expiry = date.fromisoformat(
                raw_value
            )
        except ValueError:
            continue

        if expiry >= trading_date:
            expiries.append(
                expiry
            )

    if not expiries:
        raise RuntimeError(
            "No valid NIFTY option expiry returned by Dhan"
        )

    return min(
        expiries
    )


def make_selector() -> OptionSelector:
    return OptionSelector(
        expiry_policy=ExpirySelectionPolicy(),
        delta_filter=DeltaEligibilityFilter(),
        contract_ranker=ContractRankingPolicy(),
    )


def make_service(
    dhan_client,
) -> OptionSelectionService:
    provider = DhanOptionChainAdapter(
        dhan_client=dhan_client,
        underlying_security_id=13,
        underlying_segment="IDX_I",
        underlying_type="INDEX",
        lot_size=65,
    )

    return OptionSelectionService(
        provider=provider,
        selector=make_selector(),
        supported_underlying=NIFTY_SYMBOL,
    )


def make_signal(
    *,
    direction: SignalDirection,
    nifty_price: float,
    generated_at: datetime,
) -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            "LIVE-M05-"
            f"{direction.value}-"
            f"{generated_at.strftime('%Y%m%d%H%M%S')}"
        ),
        trading_date=generated_at.date(),
        level=EntryLevel.K5,
        direction=direction,
        underlying_symbol=NIFTY_SYMBOL,
        underlying_security_id=NIFTY_SECURITY_ID,
        underlying_price=nifty_price,

        # This live diagnostic tests option selection only.
        # K5 itself isn't required to select the contract.
        level_price=nifty_price,

        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=generated_at,
    )


def print_selected_option(
    label: str,
    result,
) -> None:
    print()
    print("-" * 70)
    print(label)
    print("-" * 70)

    print(
        "Selection Status :",
        result.status.value,
    )

    if (
        result.status
        is not OptionSelectionStatus.SELECTED
    ):
        print(
            "Message          :",
            result.message,
        )

        return

    option = result.selected_option

    if option is None:
        print(
            "ERROR: SELECTED status returned "
            "without SelectedOption"
        )
        return

    print(
        "Symbol           :",
        option.symbol,
    )

    print(
        "Security ID      :",
        option.security_id,
    )

    print(
        "Option Type      :",
        option.option_type.value,
    )

    print(
        "Strike           :",
        option.strike,
    )

    print(
        "Expiry           :",
        option.expiry,
    )

    print(
        "LTP              :",
        option.ltp,
    )

    print(
        "Delta            :",
        option.delta,
    )

    print(
        "|Delta|          :",
        option.delta_magnitude,
    )

    print(
        "Target Delta     :",
        option.selection_delta_target,
    )

    print(
        "Lot Size         :",
        option.lot_size,
    )

    print(
        "Quote Time       :",
        option.candidate.quote.received_at,
    )

    print(
        "Greeks Time      :",
        option.candidate.greeks.calculated_at,
    )

    if option.candidate.quote.bid is not None:
        print(
            "Best Bid         :",
            option.candidate.quote.bid,
        )

    if option.candidate.quote.ask is not None:
        print(
            "Best Ask         :",
            option.candidate.quote.ask,
        )

    print(
        "Volume           :",
        option.candidate.quote.volume,
    )

    print(
        "Open Interest    :",
        option.candidate.quote.open_interest,
    )


def validate_selected_option(
    result,
    expected_type: OptionType,
) -> None:
    """
    Fail loudly if Phoenix selects something outside
    the finalized M05 constraints.
    """

    if (
        result.status
        is not OptionSelectionStatus.SELECTED
    ):
        raise RuntimeError(
            "Live option selection failed: "
            f"{result.status.value} - "
            f"{result.message}"
        )

    option = result.selected_option

    if option is None:
        raise RuntimeError(
            "SelectedOption is unexpectedly None"
        )

    if option.option_type is not expected_type:
        raise RuntimeError(
            "Wrong option side selected: "
            f"{option.option_type.value}"
        )

    if not (
        DELTA_MIN
        <= option.delta_magnitude
        <= DELTA_MAX
    ):
        raise RuntimeError(
            "Selected option violates Phoenix delta range: "
            f"{option.delta}"
        )

    if option.ltp <= 0:
        raise RuntimeError(
            "Selected option has invalid LTP"
        )

    if not option.security_id.strip():
        raise RuntimeError(
            "Selected option has empty security ID"
        )


def main() -> None:
    print()
    print("=" * 70)
    print("PHOENIX M05-T11 LIVE DHAN OPTION SELECTION TEST")
    print("=" * 70)

    print()
    print("READ ONLY")
    print("No broker order will be placed.")
    print()

    now = datetime.now()

    print(
        "Test Time         :",
        now,
    )

    print(
        "Underlying        :",
        NIFTY_SYMBOL,
    )

    print(
        "Security ID       :",
        NIFTY_SECURITY_ID,
    )

    print(
        "Delta Range       :",
        f"{DELTA_MIN:.2f} - {DELTA_MAX:.2f}",
    )

    print(
        "Preferred Delta   :",
        PREFERRED_DELTA,
    )

    # ---------------------------------------------------------
    # Dhan client
    # ---------------------------------------------------------

    dhan_client = get_dhan_client()

    print()
    print("Dhan client initialized successfully.")

    # ---------------------------------------------------------
    # Resolve real NIFTY expiry
    # ---------------------------------------------------------

    print()
    print("Fetching NIFTY expiry list...")

    raw_expiries = get_expiry_list(
        dhan_client
    )

    expiry = nearest_valid_expiry(
        raw_expiries=raw_expiries,
        trading_date=now.date(),
    )

    print(
        "Selected Expiry   :",
        expiry,
    )

    print(
        "Available Expiries:",
        raw_expiries[:5],
    )

    # Dhan option-chain requests are rate limited.
    print()
    print(
        f"Waiting {REQUEST_DELAY_SECONDS} seconds "
        "before option-chain request..."
    )

    time.sleep(
        REQUEST_DELAY_SECONDS
    )

    # ---------------------------------------------------------
    # Create service
    # ---------------------------------------------------------

    service = make_service(
        dhan_client
    )

    # ---------------------------------------------------------
    # We need a valid NIFTY reference price.
    #
    # For this diagnostic the adapter will replace this with
    # the Dhan option-chain underlying last_price internally.
    #
    # The value only needs to be positive for the request
    # domain contract.
    # ---------------------------------------------------------

    reference_price = 1.0

    # ---------------------------------------------------------
    # CALL
    # ---------------------------------------------------------

    print()
    print("Requesting live CALL option selection...")

    call_signal = make_signal(
        direction=SignalDirection.CALL,
        nifty_price=reference_price,
        generated_at=now,
    )

    call_result = service.select_for_signal(
        signal=call_signal,
        requested_at=datetime.now(),
        requested_expiry=expiry,
    )

    print_selected_option(
        "LIVE CALL SELECTION",
        call_result,
    )

    validate_selected_option(
        call_result,
        OptionType.CALL,
    )

    # ---------------------------------------------------------
    # Respect Dhan option-chain request cadence before PUT
    # ---------------------------------------------------------

    print()
    print(
        f"Waiting {REQUEST_DELAY_SECONDS} seconds "
        "before PUT request..."
    )

    time.sleep(
        REQUEST_DELAY_SECONDS
    )

    # ---------------------------------------------------------
    # PUT
    # ---------------------------------------------------------

    print()
    print("Requesting live PUT option selection...")

    put_signal = make_signal(
        direction=SignalDirection.PUT,
        nifty_price=reference_price,
        generated_at=now,
    )

    put_result = service.select_for_signal(
        signal=put_signal,
        requested_at=datetime.now(),
        requested_expiry=expiry,
    )

    print_selected_option(
        "LIVE PUT SELECTION",
        put_result,
    )

    validate_selected_option(
        put_result,
        OptionType.PUT,
    )

    # ---------------------------------------------------------
    # Final result
    # ---------------------------------------------------------

    print()
    print("=" * 70)
    print("M05-T11 LIVE TEST SUCCESS")
    print("=" * 70)

    print()
    print(
        "CALL:",
        call_result.selected_option.symbol,
        "| Delta:",
        call_result.selected_option.delta,
        "| LTP:",
        call_result.selected_option.ltp,
    )

    print(
        "PUT :",
        put_result.selected_option.symbol,
        "| Delta:",
        put_result.selected_option.delta,
        "| LTP:",
        put_result.selected_option.ltp,
    )

    print()
    print("No orders were placed.")


if __name__ == "__main__":
    main()