"""
Phoenix order eligibility validation.

Validates broker-independent OrderIntent objects before
they reach a broker execution adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from enum import Enum
from math import isfinite

from src.execution.execution_types import (
    ExecutionMode,
    OrderIntent,
    OrderType,
    TransactionType,
)
from src.execution.quantity_policy import QuantityPolicy


class OrderEligibilityReason(str, Enum):
    ELIGIBLE = "ELIGIBLE"

    TRADING_DISABLED = "TRADING_DISABLED"
    PLATFORM_HALTED = "PLATFORM_HALTED"

    BEFORE_EXECUTION_WINDOW = "BEFORE_EXECUTION_WINDOW"
    AFTER_EXECUTION_WINDOW = "AFTER_EXECUTION_WINDOW"

    INVALID_TRANSACTION_TYPE = "INVALID_TRANSACTION_TYPE"
    INVALID_ORDER_TYPE = "INVALID_ORDER_TYPE"

    SIDE_MISMATCH = "SIDE_MISMATCH"

    INVALID_QUANTITY = "INVALID_QUANTITY"

    INVALID_OPTION_LTP = "INVALID_OPTION_LTP"
    INVALID_LIMIT_PRICE = "INVALID_LIMIT_PRICE"

    LIMIT_BELOW_OPTION_LTP = "LIMIT_BELOW_OPTION_LTP"

    INVALID_EXECUTION_MODE = "INVALID_EXECUTION_MODE"

    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    LIVE_EXECUTION_DISABLED = "LIVE_EXECUTION_DISABLED"


@dataclass(frozen=True, slots=True)
class OrderEligibilityContext:
    """
    Runtime conditions governing whether orders may proceed.
    """

    trading_enabled: bool = True
    platform_halted: bool = False


@dataclass(frozen=True, slots=True)
class OrderEligibilityResult:
    """
    Result from OrderEligibilityValidator.
    """

    eligible: bool

    reason: OrderEligibilityReason

    message: str | None = None


class OrderEligibilityValidator:
    """
    Validates an OrderIntent before broker submission.

    Current Phoenix execution window:

        start      : 09:20
        force exit : 15:15

    New BUY entries are permitted from 09:20 inclusive
    until 15:15 exclusive.
    """

    def __init__(
        self,
        quantity_policy: QuantityPolicy | None = None,
        start_time: time = time(9, 20),
        force_exit_time: time = time(15, 15),
    ) -> None:
        if start_time >= force_exit_time:
            raise ValueError(
                "start_time must be before force_exit_time"
            )

        self._quantity_policy = (
            quantity_policy or QuantityPolicy()
        )

        self._start_time = start_time
        self._force_exit_time = force_exit_time

    def validate(
        self,
        intent: OrderIntent,
        context: OrderEligibilityContext,
    ) -> OrderEligibilityResult:
        """
        Validate one broker-independent order intent.
        """

        if not context.trading_enabled:
            return self._reject(
                OrderEligibilityReason.TRADING_DISABLED,
                "trading is disabled",
            )

        if context.platform_halted:
            return self._reject(
                OrderEligibilityReason.PLATFORM_HALTED,
                "platform is halted",
            )

        current_time = intent.created_at.time()

        if current_time < self._start_time:
            return self._reject(
                OrderEligibilityReason.BEFORE_EXECUTION_WINDOW,
                "order created before execution window",
            )

        if current_time >= self._force_exit_time:
            return self._reject(
                OrderEligibilityReason.AFTER_EXECUTION_WINDOW,
                "new order created at or after force-exit time",
            )

        if intent.transaction_type is not TransactionType.BUY:
            return self._reject(
                OrderEligibilityReason.INVALID_TRANSACTION_TYPE,
                "Phoenix currently supports BUY orders only",
            )

        if intent.order_type is not OrderType.LIMIT:
            return self._reject(
                OrderEligibilityReason.INVALID_ORDER_TYPE,
                "Phoenix currently supports LIMIT orders only",
            )

        if (
            intent.signal.direction.value
            != intent.selected_option.option_type.value
        ):
            return self._reject(
                OrderEligibilityReason.SIDE_MISMATCH,
                "signal direction and selected option type do not match",
            )

        quantity_result = self._quantity_policy.validate(
            selected_option=intent.selected_option,
            quantity=intent.quantity,
        )

        if not quantity_result.valid:
            return self._reject(
                OrderEligibilityReason.INVALID_QUANTITY,
                quantity_result.message
                or "execution quantity is invalid",
            )

        option_ltp = intent.selected_option.ltp

        if (
            not isfinite(option_ltp)
            or option_ltp <= 0
        ):
            return self._reject(
                OrderEligibilityReason.INVALID_OPTION_LTP,
                "selected option LTP is invalid",
            )

        if (
            not isfinite(intent.limit_price)
            or intent.limit_price <= 0
        ):
            return self._reject(
                OrderEligibilityReason.INVALID_LIMIT_PRICE,
                "limit price is invalid",
            )

        if intent.limit_price < option_ltp:
            return self._reject(
                OrderEligibilityReason.LIMIT_BELOW_OPTION_LTP,
                "BUY limit price cannot be below selected option LTP",
            )

        if intent.execution_mode not in {
            ExecutionMode.DRY_RUN,
            ExecutionMode.LIVE,
        }:
            return self._reject(
                OrderEligibilityReason.INVALID_EXECUTION_MODE,
                "unsupported execution mode",
            )

        return OrderEligibilityResult(
            eligible=True,
            reason=OrderEligibilityReason.ELIGIBLE,
        )

    @staticmethod
    def _reject(
        reason: OrderEligibilityReason,
        message: str,
    ) -> OrderEligibilityResult:
        return OrderEligibilityResult(
            eligible=False,
            reason=reason,
            message=message,
        )