"""
Dhan historical intraday candle adapter.

Normalizes Dhan /charts/intraday responses into the
broker-independent Phoenix HistoricalCandle model.

No strategy, option-selection, or execution logic belongs here.
"""

from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
    timezone,
)
from math import isfinite
from typing import Any

from src.market.candle_builder import (
    HistoricalCandle,
)


class DhanIntradayCandleAdapter:
    """
    Dhan implementation for completed NIFTY option
    one-minute historical candles.

    Phoenix Phase 1 scope:
        exchange segment : NSE_FNO
        instrument       : OPTIDX
        interval         : 1 minute
    """

    EXCHANGE_SEGMENT = "NSE_FNO"
    INSTRUMENT_TYPE = "OPTIDX"
    INTERVAL_MINUTES = 1

    _IST = timezone(
        timedelta(
            hours=5,
            minutes=30,
        )
    )

    def __init__(
        self,
        dhan_client: Any,
    ) -> None:
        if dhan_client is None:
            raise ValueError(
                "dhan_client cannot be None"
            )

        self._dhan = dhan_client

    def get_one_minute_candle(
        self,
        *,
        security_id: str,
        symbol: str,
        candle_start: datetime,
        requested_at: datetime,
    ) -> HistoricalCandle:
        """
        Fetch one completed one-minute option candle.

        The requested candle must already be complete.
        The exact candle-start timestamp must be present in the
        Dhan response; Phoenix never substitutes another minute.
        """

        security_id = security_id.strip()
        symbol = symbol.strip()

        if not security_id:
            raise ValueError(
                "security_id cannot be empty"
            )

        if not symbol:
            raise ValueError(
                "symbol cannot be empty"
            )

        if type(candle_start) is not datetime:
            raise TypeError(
                "candle_start must be a datetime"
            )

        if type(requested_at) is not datetime:
            raise TypeError(
                "requested_at must be a datetime"
            )

        candle_end = (
            candle_start
            + timedelta(
                minutes=self.INTERVAL_MINUTES
            )
        )

        if requested_at < candle_end:
            raise RuntimeError(
                "historical candle cannot be requested "
                "before candle completion"
            )

        if (
            requested_at.date()
            != candle_start.date()
        ):
            raise RuntimeError(
                "requested_at date must match candle_start date"
            )

        response = self._dhan.intraday_minute_data(
            security_id=security_id,
            exchange_segment=self.EXCHANGE_SEGMENT,
            instrument_type=self.INSTRUMENT_TYPE,
            from_date=self._format_datetime(
                candle_start
            ),
            to_date=self._format_datetime(
                candle_end
            ),
            interval=self.INTERVAL_MINUTES,
            oi=False,
        )

        payload = self._extract_payload(
            response
        )

        arrays = self._extract_arrays(
            payload
        )

        matching_indexes = []

        for index, raw_timestamp in enumerate(
            arrays["timestamp"]
        ):
            timestamp = self._parse_epoch(
                raw_timestamp
            )

            if timestamp == candle_start:
                matching_indexes.append(
                    index
                )

        if not matching_indexes:
            raise RuntimeError(
                "Dhan response does not contain the exact "
                "requested candle timestamp"
            )

        if len(matching_indexes) != 1:
            raise RuntimeError(
                "Dhan response contains duplicate requested "
                "candle timestamps"
            )

        index = matching_indexes[0]

        try:
            open_price = self._positive_float(
                arrays["open"][index],
                name="open",
            )

            high_price = self._positive_float(
                arrays["high"][index],
                name="high",
            )

            low_price = self._positive_float(
                arrays["low"][index],
                name="low",
            )

            close_price = self._positive_float(
                arrays["close"][index],
                name="close",
            )

        except (
            IndexError,
            TypeError,
            ValueError,
        ) as exc:
            raise RuntimeError(
                "Dhan historical candle OHLC is invalid"
            ) from exc

        return HistoricalCandle(
            security_id=security_id,
            symbol=symbol,
            start_time=candle_start,
            end_time=candle_end,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
        )

    @classmethod
    def _parse_epoch(
        cls,
        value: Any,
    ) -> datetime:
        if isinstance(value, bool):
            raise RuntimeError(
                "Dhan historical timestamp is invalid"
            )

        try:
            epoch = int(value)
        except (
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            raise RuntimeError(
                "Dhan historical timestamp is invalid"
            ) from exc

        if epoch <= 0:
            raise RuntimeError(
                "Dhan historical timestamp is invalid"
            )

        try:
            aware = datetime.fromtimestamp(
                epoch,
                tz=timezone.utc,
            )

        except (
            OSError,
            OverflowError,
            ValueError,
        ) as exc:
            raise RuntimeError(
                "Dhan historical timestamp is invalid"
            ) from exc

        return (
            aware
            .astimezone(cls._IST)
            .replace(
                tzinfo=None
            )
        )

    @staticmethod
    def _format_datetime(
        value: datetime,
    ) -> str:
        return value.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    @classmethod
    def _extract_payload(
        cls,
        response: Any,
    ) -> dict[str, Any]:
        """
        Accept the documented direct historical payload while
        also tolerating successful SDK-style data envelopes.
        """

        if not isinstance(
            response,
            dict,
        ):
            raise RuntimeError(
                "Dhan historical data returned invalid response"
            )

        current: Any = response

        for _ in range(4):
            if not isinstance(
                current,
                dict,
            ):
                break

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
                    "Dhan historical data failed: "
                    f"{remarks if remarks else current}"
                )

            if cls._looks_like_payload(
                current
            ):
                return current

            if "data" not in current:
                break

            current = current["data"]

        if (
            isinstance(current, dict)
            and cls._looks_like_payload(
                current
            )
        ):
            return current

        raise RuntimeError(
            "Dhan historical response missing OHLC arrays"
        )

    @staticmethod
    def _looks_like_payload(
        value: dict[str, Any],
    ) -> bool:
        return all(
            key in value
            for key in (
                "open",
                "high",
                "low",
                "close",
                "timestamp",
            )
        )

    @staticmethod
    def _extract_arrays(
        payload: dict[str, Any],
    ) -> dict[str, list[Any]]:
        required = (
            "open",
            "high",
            "low",
            "close",
            "timestamp",
        )

        arrays: dict[
            str,
            list[Any],
        ] = {}

        for key in required:
            value = payload.get(
                key
            )

            if not isinstance(
                value,
                list,
            ):
                raise RuntimeError(
                    "Dhan historical response "
                    f"{key} must be a list"
                )

            arrays[key] = value

        lengths = {
            len(value)
            for value in arrays.values()
        }

        if len(lengths) != 1:
            raise RuntimeError(
                "Dhan historical response arrays "
                "have inconsistent lengths"
            )

        if not arrays["timestamp"]:
            raise RuntimeError(
                "Dhan historical response contains no candles"
            )

        return arrays

    @staticmethod
    def _positive_float(
        value: Any,
        *,
        name: str,
    ) -> float:
        if isinstance(value, bool):
            raise ValueError(
                f"{name} is invalid"
            )

        try:
            parsed = float(
                value
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                f"{name} is invalid"
            ) from exc

        if (
            not isfinite(parsed)
            or parsed <= 0
        ):
            raise ValueError(
                f"{name} is invalid"
            )

        return parsed
