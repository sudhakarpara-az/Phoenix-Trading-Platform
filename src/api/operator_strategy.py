"""
Passive M13 strategy and option-selection dashboard projection.

The service reads exact already-prepared M03/M05/M10 objects.
It never recalculates KS levels, selects options, requests
broker data, persists state, or mutates the trading runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Protocol

from src.option_selection.option_types import (
    OptionType,
    SelectedOption,
)
from src.services.scheduler import (
    TradingDayLevelPreparationResult,
)
from src.strategy.strategy_types import (
    KSLevels,
)


class OperatorSelectedOptionReader(
    Protocol
):
    @property
    def selected_call(
        self,
    ) -> SelectedOption:
        ...

    @property
    def selected_put(
        self,
    ) -> SelectedOption:
        ...


class OperatorLevelPreparationReader(
    Protocol
):
    @property
    def level_preparation(
        self,
    ) -> TradingDayLevelPreparationResult:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorSelectedOptionView:
    underlying_symbol: str
    symbol: str
    security_id: str
    option_type: str

    strike: float
    expiry: date
    lot_size: int

    delta: float
    delta_magnitude: float

    selection_ltp: float
    selected_at: datetime
    selection_delta_target: float


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorKSLevelsView:
    trading_date: date

    instrument_security_id: str
    instrument_symbol: str

    high_915: float
    low_915: float
    close_915: float

    n1: float
    n2: float
    c1: float

    e_level: float
    t_level: float

    k0: float
    k1: float
    k2: float
    k3: float
    k5: float
    k6: float
    k7: float

    calculated_at: datetime
    formula_version: str


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorStrategyView:
    trading_date: date
    expiry: date

    selected_call: OperatorSelectedOptionView
    selected_put: OperatorSelectedOptionView

    call_levels: OperatorKSLevelsView
    put_levels: OperatorKSLevelsView

    prepared_at: datetime
    captured_at: datetime

    is_ready: bool


class OperatorStrategyService:
    """
    Project one internally coherent prepared trading-day view.

    signal_runtime and entry_runtime must expose the same exact
    SelectedOption instances originating from the authoritative
    TradingDayLevelPreparationResult.
    """

    def __init__(
        self,
        *,
        signal_runtime:
            OperatorSelectedOptionReader,
        entry_runtime:
            OperatorLevelPreparationReader,
    ) -> None:
        self._signal_runtime = (
            signal_runtime
        )

        self._entry_runtime = (
            entry_runtime
        )

    @property
    def signal_runtime(
        self,
    ) -> OperatorSelectedOptionReader:
        return self._signal_runtime

    @property
    def entry_runtime(
        self,
    ) -> OperatorLevelPreparationReader:
        return self._entry_runtime

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorStrategyView:
        if not isinstance(
            captured_at,
            datetime,
        ):
            raise TypeError(
                "captured_at must be datetime"
            )

        preparation = (
            self._entry_runtime
            .level_preparation
        )

        if not isinstance(
            preparation,
            TradingDayLevelPreparationResult,
        ):
            raise TypeError(
                "entry runtime returned invalid "
                "TradingDayLevelPreparationResult"
            )

        selected_call = (
            self._signal_runtime
            .selected_call
        )

        selected_put = (
            self._signal_runtime
            .selected_put
        )

        if not isinstance(
            selected_call,
            SelectedOption,
        ):
            raise TypeError(
                "signal runtime returned invalid "
                "selected CALL"
            )

        if not isinstance(
            selected_put,
            SelectedOption,
        ):
            raise TypeError(
                "signal runtime returned invalid "
                "selected PUT"
            )

        if (
            preparation.selected_call
            is not selected_call
        ):
            raise ValueError(
                "selected CALL must be the exact "
                "prepared CALL instance"
            )

        if (
            preparation.selected_put
            is not selected_put
        ):
            raise ValueError(
                "selected PUT must be the exact "
                "prepared PUT instance"
            )

        if (
            selected_call.option_type
            is not OptionType.CALL
        ):
            raise ValueError(
                "selected_call must be CALL"
            )

        if (
            selected_put.option_type
            is not OptionType.PUT
        ):
            raise ValueError(
                "selected_put must be PUT"
            )

        if (
            selected_call.expiry
            != selected_put.expiry
        ):
            raise ValueError(
                "selected CALL and PUT expiry "
                "must match"
            )

        call_levels = (
            preparation.call_levels
        )

        put_levels = (
            preparation.put_levels
        )

        if not isinstance(
            call_levels,
            KSLevels,
        ):
            raise TypeError(
                "call_levels must be KSLevels"
            )

        if not isinstance(
            put_levels,
            KSLevels,
        ):
            raise TypeError(
                "put_levels must be KSLevels"
            )

        if (
            call_levels
            .instrument_security_id
            != selected_call.security_id
        ):
            raise ValueError(
                "CALL levels must match selected CALL"
            )

        if (
            put_levels
            .instrument_security_id
            != selected_put.security_id
        ):
            raise ValueError(
                "PUT levels must match selected PUT"
            )

        if (
            call_levels.trading_date
            != put_levels.trading_date
        ):
            raise ValueError(
                "CALL and PUT levels trading date "
                "must match"
            )

        if not preparation.is_ready:
            raise ValueError(
                "level preparation must be ready"
            )

        return OperatorStrategyView(
            trading_date=(
                call_levels.trading_date
            ),
            expiry=(
                selected_call.expiry
            ),
            selected_call=(
                self._map_option(
                    selected_call
                )
            ),
            selected_put=(
                self._map_option(
                    selected_put
                )
            ),
            call_levels=(
                self._map_levels(
                    call_levels
                )
            ),
            put_levels=(
                self._map_levels(
                    put_levels
                )
            ),
            prepared_at=(
                preparation.prepared_at
            ),
            captured_at=captured_at,
            is_ready=True,
        )

    @staticmethod
    def _map_option(
        selected: SelectedOption,
    ) -> OperatorSelectedOptionView:
        contract = selected.contract

        return OperatorSelectedOptionView(
            underlying_symbol=(
                contract.underlying_symbol
            ),
            symbol=selected.symbol,
            security_id=(
                selected.security_id
            ),
            option_type=(
                selected.option_type.value
            ),
            strike=float(
                selected.strike
            ),
            expiry=selected.expiry,
            lot_size=selected.lot_size,
            delta=float(
                selected.delta
            ),
            delta_magnitude=float(
                selected.delta_magnitude
            ),
            selection_ltp=float(
                selected.ltp
            ),
            selected_at=(
                selected.selected_at
            ),
            selection_delta_target=float(
                selected
                .selection_delta_target
            ),
        )

    @staticmethod
    def _map_levels(
        levels: KSLevels,
    ) -> OperatorKSLevelsView:
        return OperatorKSLevelsView(
            trading_date=levels.trading_date,
            instrument_security_id=(
                levels
                .instrument_security_id
            ),
            instrument_symbol=(
                levels.instrument_symbol
            ),
            high_915=float(
                levels.high_915
            ),
            low_915=float(
                levels.low_915
            ),
            close_915=float(
                levels.close_915
            ),
            n1=float(
                levels.n1
            ),
            n2=float(
                levels.n2
            ),
            c1=float(
                levels.c1
            ),
            e_level=float(
                levels.e_level
            ),
            t_level=float(
                levels.t_level
            ),
            k0=float(
                levels.k0
            ),
            k1=float(
                levels.k1
            ),
            k2=float(
                levels.k2
            ),
            k3=float(
                levels.k3
            ),
            k5=float(
                levels.k5
            ),
            k6=float(
                levels.k6
            ),
            k7=float(
                levels.k7
            ),
            calculated_at=(
                levels.calculated_at
            ),
            formula_version=(
                levels.formula_version
            ),
        )


__all__ = [
    "OperatorKSLevelsView",
    "OperatorLevelPreparationReader",
    "OperatorSelectedOptionReader",
    "OperatorSelectedOptionView",
    "OperatorStrategyService",
    "OperatorStrategyView",
]
