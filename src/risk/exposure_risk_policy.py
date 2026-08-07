"""
Phoenix M07 exposure / quantity risk policy.

Evaluates whether a proposed additional long-option position
fits within configured M07 exposure limits.

Responsibilities:
    - maximum open positions
    - maximum aggregate open quantity
    - maximum quantity per position
    - maximum monetary risk per position
    - maximum aggregate monetary risk

No broker calls or order placement belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
)


@dataclass(frozen=True, slots=True)
class ExposureRiskConfig:
    """
    M07 configurable exposure limits.

    None means the particular limit is disabled.
    """

    max_open_positions: int | None = None

    max_total_open_quantity: int | None = None

    max_position_quantity: int | None = None

    max_position_risk_amount: float | None = None

    max_total_risk_amount: float | None = None

    def __post_init__(self) -> None:
        integer_limits = {
            "max_open_positions": (
                self.max_open_positions
            ),
            "max_total_open_quantity": (
                self.max_total_open_quantity
            ),
            "max_position_quantity": (
                self.max_position_quantity
            ),
        }

        for name, value in integer_limits.items():
            if value is not None and value <= 0:
                raise ValueError(
                    f"{name} must be greater than zero"
                )

        monetary_limits = {
            "max_position_risk_amount": (
                self.max_position_risk_amount
            ),
            "max_total_risk_amount": (
                self.max_total_risk_amount
            ),
        }

        for name, value in monetary_limits.items():
            if value is None:
                continue

            if not isfinite(value):
                raise ValueError(
                    f"{name} must be finite"
                )

            if value <= 0:
                raise ValueError(
                    f"{name} must be greater than zero"
                )


class ExposureRiskReason(str, Enum):
    ELIGIBLE = "ELIGIBLE"

    INVALID_QUANTITY = "INVALID_QUANTITY"

    STOP_LOSS_REQUIRED = "STOP_LOSS_REQUIRED"

    MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS"

    MAX_TOTAL_OPEN_QUANTITY = (
        "MAX_TOTAL_OPEN_QUANTITY"
    )

    MAX_POSITION_QUANTITY = (
        "MAX_POSITION_QUANTITY"
    )

    MAX_POSITION_RISK = (
        "MAX_POSITION_RISK"
    )

    MAX_TOTAL_RISK = (
        "MAX_TOTAL_RISK"
    )


@dataclass(frozen=True, slots=True)
class ExposureRiskDecision:
    eligible: bool

    reason: ExposureRiskReason

    proposed_quantity: int

    proposed_risk_amount: float | None

    existing_open_positions: int

    projected_open_positions: int

    existing_open_quantity: int

    projected_open_quantity: int

    existing_total_risk_amount: float

    projected_total_risk_amount: float | None

    message: str | None = None


class ExposureRiskPolicy:
    """
    Evaluates proposed position exposure against current
    PositionRegistry state.
    """

    def __init__(
        self,
        *,
        registry: PositionRegistry,
        config: ExposureRiskConfig | None = None,
    ) -> None:
        self._registry = registry

        self._config = (
            config
            or ExposureRiskConfig()
        )

    @property
    def config(
        self,
    ) -> ExposureRiskConfig:
        return self._config

    def evaluate_new_position(
        self,
        *,
        quantity: int,
        stop_risk_points: float | None,
    ) -> ExposureRiskDecision:
        """
        Evaluate a proposed new long-option position.

        stop_risk_points must represent the effective
        entry-to-stop risk per option unit after tick rounding.
        """

        open_positions = (
            self._registry.open_positions()
        )

        existing_open_positions = len(
            open_positions
        )

        existing_open_quantity = sum(
            position.open_quantity
            for position in open_positions
        )

        existing_total_risk_amount = sum(
            self._position_risk_amount(
                position
            )
            for position in open_positions
        )

        projected_open_positions = (
            existing_open_positions
            + 1
        )

        if quantity <= 0:
            return self._reject(
                reason=(
                    ExposureRiskReason
                    .INVALID_QUANTITY
                ),
                quantity=quantity,
                proposed_risk_amount=None,
                existing_open_positions=(
                    existing_open_positions
                ),
                projected_open_positions=(
                    projected_open_positions
                ),
                existing_open_quantity=(
                    existing_open_quantity
                ),
                projected_open_quantity=(
                    existing_open_quantity
                ),
                existing_total_risk_amount=(
                    existing_total_risk_amount
                ),
                projected_total_risk_amount=None,
                message=(
                    "proposed quantity must be "
                    "greater than zero"
                ),
            )

        projected_open_quantity = (
            existing_open_quantity
            + quantity
        )

        if stop_risk_points is None:
            return self._reject(
                reason=(
                    ExposureRiskReason
                    .STOP_LOSS_REQUIRED
                ),
                quantity=quantity,
                proposed_risk_amount=None,
                existing_open_positions=(
                    existing_open_positions
                ),
                projected_open_positions=(
                    projected_open_positions
                ),
                existing_open_quantity=(
                    existing_open_quantity
                ),
                projected_open_quantity=(
                    projected_open_quantity
                ),
                existing_total_risk_amount=(
                    existing_total_risk_amount
                ),
                projected_total_risk_amount=None,
                message=(
                    "new position risk evaluation "
                    "requires stop-loss risk points"
                ),
            )

        if not isfinite(
            stop_risk_points
        ):
            raise ValueError(
                "stop_risk_points must be finite"
            )

        if stop_risk_points <= 0:
            raise ValueError(
                "stop_risk_points must be "
                "greater than zero"
            )

        proposed_risk_amount = (
            stop_risk_points
            * quantity
        )

        projected_total_risk_amount = (
            existing_total_risk_amount
            + proposed_risk_amount
        )

        # ----------------------------------------------
        # Per-position quantity
        # ----------------------------------------------

        if (
            self._config.max_position_quantity
            is not None
            and quantity
            > self._config.max_position_quantity
        ):
            return self._reject(
                reason=(
                    ExposureRiskReason
                    .MAX_POSITION_QUANTITY
                ),
                quantity=quantity,
                proposed_risk_amount=(
                    proposed_risk_amount
                ),
                existing_open_positions=(
                    existing_open_positions
                ),
                projected_open_positions=(
                    projected_open_positions
                ),
                existing_open_quantity=(
                    existing_open_quantity
                ),
                projected_open_quantity=(
                    projected_open_quantity
                ),
                existing_total_risk_amount=(
                    existing_total_risk_amount
                ),
                projected_total_risk_amount=(
                    projected_total_risk_amount
                ),
                message=(
                    "proposed quantity exceeds "
                    "per-position limit"
                ),
            )

        # ----------------------------------------------
        # Open position count
        # ----------------------------------------------

        if (
            self._config.max_open_positions
            is not None
            and projected_open_positions
            > self._config.max_open_positions
        ):
            return self._reject(
                reason=(
                    ExposureRiskReason
                    .MAX_OPEN_POSITIONS
                ),
                quantity=quantity,
                proposed_risk_amount=(
                    proposed_risk_amount
                ),
                existing_open_positions=(
                    existing_open_positions
                ),
                projected_open_positions=(
                    projected_open_positions
                ),
                existing_open_quantity=(
                    existing_open_quantity
                ),
                projected_open_quantity=(
                    projected_open_quantity
                ),
                existing_total_risk_amount=(
                    existing_total_risk_amount
                ),
                projected_total_risk_amount=(
                    projected_total_risk_amount
                ),
                message=(
                    "projected open position count "
                    "exceeds configured limit"
                ),
            )

        # ----------------------------------------------
        # Aggregate quantity
        # ----------------------------------------------

        if (
            self._config.max_total_open_quantity
            is not None
            and projected_open_quantity
            > self._config.max_total_open_quantity
        ):
            return self._reject(
                reason=(
                    ExposureRiskReason
                    .MAX_TOTAL_OPEN_QUANTITY
                ),
                quantity=quantity,
                proposed_risk_amount=(
                    proposed_risk_amount
                ),
                existing_open_positions=(
                    existing_open_positions
                ),
                projected_open_positions=(
                    projected_open_positions
                ),
                existing_open_quantity=(
                    existing_open_quantity
                ),
                projected_open_quantity=(
                    projected_open_quantity
                ),
                existing_total_risk_amount=(
                    existing_total_risk_amount
                ),
                projected_total_risk_amount=(
                    projected_total_risk_amount
                ),
                message=(
                    "projected open quantity exceeds "
                    "configured aggregate limit"
                ),
            )

        # ----------------------------------------------
        # Per-position monetary risk
        # ----------------------------------------------

        if (
            self._config.max_position_risk_amount
            is not None
            and proposed_risk_amount
            > self._config.max_position_risk_amount
        ):
            return self._reject(
                reason=(
                    ExposureRiskReason
                    .MAX_POSITION_RISK
                ),
                quantity=quantity,
                proposed_risk_amount=(
                    proposed_risk_amount
                ),
                existing_open_positions=(
                    existing_open_positions
                ),
                projected_open_positions=(
                    projected_open_positions
                ),
                existing_open_quantity=(
                    existing_open_quantity
                ),
                projected_open_quantity=(
                    projected_open_quantity
                ),
                existing_total_risk_amount=(
                    existing_total_risk_amount
                ),
                projected_total_risk_amount=(
                    projected_total_risk_amount
                ),
                message=(
                    "proposed position monetary risk "
                    "exceeds configured limit"
                ),
            )

        # ----------------------------------------------
        # Aggregate monetary risk
        # ----------------------------------------------

        if (
            self._config.max_total_risk_amount
            is not None
            and projected_total_risk_amount
            > self._config.max_total_risk_amount
        ):
            return self._reject(
                reason=(
                    ExposureRiskReason
                    .MAX_TOTAL_RISK
                ),
                quantity=quantity,
                proposed_risk_amount=(
                    proposed_risk_amount
                ),
                existing_open_positions=(
                    existing_open_positions
                ),
                projected_open_positions=(
                    projected_open_positions
                ),
                existing_open_quantity=(
                    existing_open_quantity
                ),
                projected_open_quantity=(
                    projected_open_quantity
                ),
                existing_total_risk_amount=(
                    existing_total_risk_amount
                ),
                projected_total_risk_amount=(
                    projected_total_risk_amount
                ),
                message=(
                    "projected aggregate monetary risk "
                    "exceeds configured limit"
                ),
            )

        return ExposureRiskDecision(
            eligible=True,
            reason=ExposureRiskReason.ELIGIBLE,
            proposed_quantity=quantity,
            proposed_risk_amount=(
                proposed_risk_amount
            ),
            existing_open_positions=(
                existing_open_positions
            ),
            projected_open_positions=(
                projected_open_positions
            ),
            existing_open_quantity=(
                existing_open_quantity
            ),
            projected_open_quantity=(
                projected_open_quantity
            ),
            existing_total_risk_amount=(
                existing_total_risk_amount
            ),
            projected_total_risk_amount=(
                projected_total_risk_amount
            ),
            message=None,
        )

    @staticmethod
    def _position_risk_amount(
        position: ManagedPosition,
    ) -> float:
        """
        Return configured remaining monetary risk for one
        managed open position.

        A position without an armed/configured stop contributes
        zero here because it should not normally exist once M07
        registration/risk initialization is fully integrated.

        Later M07 daily-risk logic may choose to treat missing
        stop state as a hard risk fault.
        """

        stop = position.stop_loss

        if stop is None:
            return 0.0

        return (
            stop.risk_points
            * position.open_quantity
        )

    @staticmethod
    def _reject(
        *,
        reason: ExposureRiskReason,
        quantity: int,
        proposed_risk_amount: float | None,
        existing_open_positions: int,
        projected_open_positions: int,
        existing_open_quantity: int,
        projected_open_quantity: int,
        existing_total_risk_amount: float,
        projected_total_risk_amount: float | None,
        message: str,
    ) -> ExposureRiskDecision:
        return ExposureRiskDecision(
            eligible=False,
            reason=reason,
            proposed_quantity=quantity,
            proposed_risk_amount=(
                proposed_risk_amount
            ),
            existing_open_positions=(
                existing_open_positions
            ),
            projected_open_positions=(
                projected_open_positions
            ),
            existing_open_quantity=(
                existing_open_quantity
            ),
            projected_open_quantity=(
                projected_open_quantity
            ),
            existing_total_risk_amount=(
                existing_total_risk_amount
            ),
            projected_total_risk_amount=(
                projected_total_risk_amount
            ),
            message=message,
        )