"""
Dhan option-chain adapter for Phoenix Trading Platform.

Translates Dhan option-chain responses into the broker-independent
Phoenix OptionChainSnapshot / OptionCandidate domain models.

No option-selection ranking or order execution belongs here.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.option_selection.option_chain_provider import (
    OptionChainProvider,
    OptionChainRequest,
    OptionChainSnapshot,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
)


class DhanOptionChainAdapter(OptionChainProvider):
    """
    Dhan implementation of OptionChainProvider.

    Phoenix currently supports:
        underlying       : NIFTY 50
        security id      : 13
        Dhan REST segment: IDX_I
        underlying type  : INDEX
        lot size         : configurable, default 65

    The adapter:
        1. Resolves expiry when request.expiry is absent.
        2. Calls Dhan option-chain API.
        3. Converts CE/PE entries into Phoenix models.
        4. Skips unusable contracts with invalid LTP/delta/security ID.
    """

    def __init__(
        self,
        dhan_client: Any,
        underlying_security_id: int = 13,
        underlying_segment: str = "IDX_I",
        underlying_type: str = "INDEX",
        lot_size: int = 65,
    ) -> None:
        if dhan_client is None:
            raise ValueError(
                "dhan_client cannot be None"
            )

        if underlying_security_id <= 0:
            raise ValueError(
                "underlying_security_id must be greater than zero"
            )

        if not underlying_segment.strip():
            raise ValueError(
                "underlying_segment cannot be empty"
            )

        if not underlying_type.strip():
            raise ValueError(
                "underlying_type cannot be empty"
            )

        if lot_size <= 0:
            raise ValueError(
                "lot_size must be greater than zero"
            )

        self._dhan = dhan_client
        self._underlying_security_id = underlying_security_id
        self._underlying_segment = underlying_segment.strip()
        self._underlying_type = underlying_type.strip()
        self._lot_size = lot_size

    @property
    def provider_name(self) -> str:
        return "DHAN"

    def get_option_chain(
        self,
        request: OptionChainRequest,
    ) -> OptionChainSnapshot:
        """
        Fetch and normalize one Dhan option-chain snapshot.
        """

        expiry = request.expiry

        if expiry is None:
            expiry = self._resolve_nearest_expiry(
                trading_date=request.requested_at.date()
            )

        raw_response = self._fetch_option_chain(
            expiry=expiry
        )

        data = self._extract_success_data(
            raw_response,
            operation="option chain",
        )

        raw_chain = data.get("oc")

        if not isinstance(raw_chain, dict):
            raise RuntimeError(
                "Dhan option chain response missing data.oc"
            )

        reference_price = self._to_positive_float(
            data.get("last_price")
        )

        if reference_price is None:
            # Keep the M04 signal price as fallback when
            # Dhan doesn't provide a usable underlying price.
            reference_price = request.reference_price

        candidates = self._parse_candidates(
            raw_chain=raw_chain,
            request=request,
            expiry=expiry,
            received_at=request.requested_at,
        )

        return OptionChainSnapshot(
            underlying_symbol=request.underlying_symbol,
            reference_price=reference_price,
            candidates=candidates,
            received_at=request.requested_at,
            provider_name=self.provider_name,
        )

    def _resolve_nearest_expiry(
        self,
        trading_date: date,
    ) -> date:
        raw_response = self._fetch_expiry_list()

        data = self._extract_success_data(
            raw_response,
            operation="expiry list",
        )

        if not isinstance(data, list):
            raise RuntimeError(
                "Dhan expiry list response missing data list"
            )

        expiries: list[date] = []

        for value in data:
            try:
                expiry = date.fromisoformat(
                    str(value)
                )
            except (TypeError, ValueError):
                continue

            if expiry >= trading_date:
                expiries.append(expiry)

        if not expiries:
            raise RuntimeError(
                "Dhan returned no valid option expiry"
            )

        return min(expiries)

    def _fetch_expiry_list(self) -> dict:
        """
        Support the current high-level SDK and older
        OptionChain-style SDK method naming.
        """

        if hasattr(
            self._dhan,
            "get_expiry_list",
        ):
            return self._dhan.get_expiry_list(
                underlying_security_id=(
                    self._underlying_security_id
                ),
                underlying_type=(
                    self._underlying_type
                ),
            )

        if hasattr(
            self._dhan,
            "expiry_list",
        ):
            return self._dhan.expiry_list(
                self._underlying_security_id,
                self._underlying_segment,
            )

        raise RuntimeError(
            "Dhan client does not expose an expiry-list API"
        )

    def _fetch_option_chain(
        self,
        expiry: date,
    ) -> dict:
        expiry_text = expiry.isoformat()

        if hasattr(
            self._dhan,
            "option_chain",
        ):
            response = self._dhan.option_chain(
                under_security_id=(
                    self._underlying_security_id
                ),
                under_exchange_segment=(
                    self._underlying_segment
                ),
                expiry=expiry_text,
            )

        elif hasattr(
            self._dhan,
            "get_option_chain",
        ):
            response = self._dhan.get_option_chain(
                underlying_security_id=(
                    self._underlying_security_id
                ),
                underlying_type=(
                    self._underlying_type
                ),
                expiry_date=expiry_text,
            )

        else:
            raise RuntimeError(
                "Dhan client does not expose an option-chain API"
            )

        return response

    def _parse_candidates(
        self,
        raw_chain: dict,
        request: OptionChainRequest,
        expiry: date,
        received_at: datetime,
    ) -> tuple[OptionCandidate, ...]:
        candidates: list[
            OptionCandidate
        ] = []

        for raw_strike, strike_data in raw_chain.items():
            if not isinstance(
                strike_data,
                dict,
            ):
                continue

            strike = self._to_positive_float(
                raw_strike
            )

            if strike is None:
                continue

            if (
                request.option_type
                is OptionType.CALL
            ):
                sides = (
                    (
                        "ce",
                        OptionType.CALL,
                    ),
                )

            else:
                sides = (
                    (
                        "pe",
                        OptionType.PUT,
                    ),
                )

            for raw_side, option_type in sides:
                option_data = strike_data.get(
                    raw_side
                )

                candidate = self._parse_candidate(
                    option_data=option_data,
                    option_type=option_type,
                    strike=strike,
                    expiry=expiry,
                    underlying_symbol=(
                        request.underlying_symbol
                    ),
                    received_at=received_at,
                )

                if candidate is not None:
                    candidates.append(
                        candidate
                    )

        return tuple(candidates)

    def _parse_candidate(
        self,
        option_data: Any,
        option_type: OptionType,
        strike: float,
        expiry: date,
        underlying_symbol: str,
        received_at: datetime,
    ) -> OptionCandidate | None:
        if not isinstance(
            option_data,
            dict,
        ):
            return None

        security_id = option_data.get(
            "security_id"
        )

        if security_id is None:
            return None

        security_id_text = str(
            security_id
        ).strip()

        if not security_id_text:
            return None

        ltp = self._to_positive_float(
            option_data.get(
                "last_price"
            )
        )

        if ltp is None:
            return None

        raw_greeks = option_data.get(
            "greeks"
        )

        if not isinstance(
            raw_greeks,
            dict,
        ):
            return None

        delta = self._to_float(
            raw_greeks.get(
                "delta"
            )
        )

        if delta is None:
            return None

        if not -1.0 <= delta <= 1.0:
            return None

        bid = self._to_non_negative_float(
            option_data.get(
                "top_bid_price"
            )
        )

        ask = self._to_non_negative_float(
            option_data.get(
                "top_ask_price"
            )
        )

        # Some feeds may temporarily report crossed/invalid
        # top-of-book values. Keep the candidate but omit
        # spread data rather than crashing normalization.
        if (
            bid is not None
            and ask is not None
            and bid > ask
        ):
            bid = None
            ask = None

        volume = self._to_non_negative_int(
            option_data.get(
                "volume"
            )
        )

        open_interest = (
            self._to_non_negative_int(
                option_data.get(
                    "oi"
                )
            )
        )

        iv = self._to_non_negative_float(
            option_data.get(
                "implied_volatility"
            )
        )

        gamma = self._to_float(
            raw_greeks.get(
                "gamma"
            )
        )

        theta = self._to_float(
            raw_greeks.get(
                "theta"
            )
        )

        vega = self._to_float(
            raw_greeks.get(
                "vega"
            )
        )

        contract = OptionContract(
            underlying_symbol=underlying_symbol,
            symbol=self._build_symbol(
                underlying_symbol=underlying_symbol,
                expiry=expiry,
                strike=strike,
                option_type=option_type,
            ),
            security_id=security_id_text,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            lot_size=self._lot_size,
        )

        quote = OptionQuote(
            ltp=ltp,
            received_at=received_at,
            bid=bid,
            ask=ask,
            volume=volume,
            open_interest=open_interest,
        )

        greeks = OptionGreeks(
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            implied_volatility=iv,
            calculated_at=received_at,
        )

        return OptionCandidate(
            contract=contract,
            quote=quote,
            greeks=greeks,
        )

    @staticmethod
    def _extract_success_data(
        response: Any,
        operation: str,
    ) -> Any:
        """
        Normalize Dhan REST and SDK wrapper responses.

        Supported examples:

        Raw REST:
            {
                "status": "success",
                "data": {...}
            }

        SDK wrapper:
            {
                "status": "success",
                "remarks": "",
                "data": {
                    "status": "success",
                    "data": {...}
                }
            }

        The method unwraps nested successful ``data`` envelopes
        while preserving the actual business payload.
        """

        if not isinstance(
            response,
            dict,
        ):
            raise RuntimeError(
                f"Dhan {operation} returned invalid response: "
                f"{response!r}"
            )

        current: Any = response

        # Dhan SDK versions may wrap the actual API response
        # inside one or more {"status": ..., "data": ...} envelopes.
        for _ in range(4):

            if not isinstance(
                current,
                dict,
            ):
                return current

            status = current.get(
                "status"
            )

            if (
                status is not None
                and str(status).lower()
                != "success"
            ):
                remarks = current.get(
                    "remarks"
                )

                raise RuntimeError(
                    f"Dhan {operation} failed: "
                    f"{remarks if remarks else current}"
                )

            if "data" not in current:
                # We have reached the actual payload object,
                # e.g. {"last_price": ..., "oc": {...}}
                return current

            data = current["data"]

            # If data is a list, that is already the actual
            # payload for expiry-list responses.
            if isinstance(
                data,
                list,
            ):
                return data

            # If data isn't a dictionary, return it and let
            # the caller validate its expected shape.
            if not isinstance(
                data,
                dict,
            ):
                return data

            # If this data object already looks like the
            # option-chain business payload, stop unwrapping.
            if (
                "oc" in data
                or "last_price" in data
            ):
                return data

            # Otherwise this is probably another SDK envelope.
            current = data

        raise RuntimeError(
            f"Dhan {operation} response exceeded "
            "supported wrapper depth"
        )

    @staticmethod
    def _build_symbol(
        underlying_symbol: str,
        expiry: date,
        strike: float,
        option_type: OptionType,
    ) -> str:
        """
        Build a stable Phoenix canonical option symbol.

        Dhan security_id remains the authoritative instrument ID.
        """

        underlying = (
            underlying_symbol
            .replace(" ", "")
            .upper()
        )

        side = (
            "CE"
            if option_type is OptionType.CALL
            else "PE"
        )

        strike_text = (
            str(int(strike))
            if strike.is_integer()
            else str(strike)
        )

        return (
            f"{underlying}-"
            f"{expiry.strftime('%Y%m%d')}-"
            f"{strike_text}-"
            f"{side}"
        )

    @staticmethod
    def _to_float(
        value: Any,
    ) -> float | None:
        try:
            parsed = float(value)
        except (
            TypeError,
            ValueError,
        ):
            return None

        if parsed != parsed:
            return None

        if parsed in (
            float("inf"),
            float("-inf"),
        ):
            return None

        return parsed

    @classmethod
    def _to_positive_float(
        cls,
        value: Any,
    ) -> float | None:
        parsed = cls._to_float(
            value
        )

        if parsed is None:
            return None

        if parsed <= 0:
            return None

        return parsed

    @classmethod
    def _to_non_negative_float(
        cls,
        value: Any,
    ) -> float | None:
        parsed = cls._to_float(
            value
        )

        if parsed is None:
            return None

        if parsed < 0:
            return None

        return parsed

    @staticmethod
    def _to_non_negative_int(
        value: Any,
    ) -> int | None:
        try:
            parsed = int(
                float(value)
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

        if parsed < 0:
            return None

        return parsed