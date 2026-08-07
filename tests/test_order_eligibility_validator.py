from datetime import date, datetime

import pytest

from src.execution.execution_types import (
    ExecutionMode,
    OrderIntent,
    OrderIntentId,
    OrderType,
    TransactionType,
)
from src.execution.order_eligibility_validator import (
    OrderEligibilityContext,
    OrderEligibilityReason,
    OrderEligibilityValidator,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
    SelectedOption,
)
from src.signals.signal_types import (
    SignalDirection,
    SignalId,
    SignalReason,
    SignalState,
    TradingSignal,
)
from src.strategy.strategy_types import EntryLevel


TRADING_DATE = date(2026, 8, 7)
EXPIRY = date(2026, 8, 11)


def make_signal(
    *,
    direction: SignalDirection = SignalDirection.CALL,
    created_at: datetime | None = None,
) -> TradingSignal:
    timestamp = created_at or datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    return TradingSignal(
        signal_id=SignalId("SIG-M06-T04"),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=direction,
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500,
        level_price=24500,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=timestamp,
    )


def make_selected_option(
    *,
    option_type: OptionType = OptionType.CALL,
    ltp: float = 205.0,
) -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol="NIFTY50-20260811-24450-CE",
                security_id="41009",
                option_type=option_type,
                strike=24450,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=ltp,
                bid=204.4,
                ask=204.9,
                volume=1000,
                open_interest=50000,
                received_at=datetime(
                    2026,
                    8,
                    7,
                    10,
                    0,
                ),
            ),
            greeks=OptionGreeks(
                delta=(
                    0.64
                    if option_type is OptionType.CALL
                    else -0.64
                ),
                calculated_at=datetime(
                    2026,
                    8,
                    7,
                    10,
                    0,
                ),
            ),
        ),
        selected_at=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
        selection_delta_target=0.64,
    )


def make_intent(
    *,
    created_at: datetime | None = None,
    quantity: int = 65,
    limit_price: float = 206.0,
    execution_mode: ExecutionMode = ExecutionMode.DRY_RUN,
) -> OrderIntent:
    timestamp = created_at or datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    return OrderIntent(
        intent_id=OrderIntentId("ORD-M06-T04"),
        signal=make_signal(
            created_at=timestamp
        ),
        selected_option=make_selected_option(),
        transaction_type=TransactionType.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=limit_price,
        execution_mode=execution_mode,
        created_at=timestamp,
    )


def test_valid_order_is_eligible() -> None:
    validator = OrderEligibilityValidator()

    result = validator.validate(
        intent=make_intent(),
        context=OrderEligibilityContext(),
    )

    assert result.eligible is True

    assert (
        result.reason
        is OrderEligibilityReason.ELIGIBLE
    )


def test_trading_disabled_is_rejected() -> None:
    validator = OrderEligibilityValidator()

    result = validator.validate(
        intent=make_intent(),
        context=OrderEligibilityContext(
            trading_enabled=False
        ),
    )

    assert result.eligible is False

    assert (
        result.reason
        is OrderEligibilityReason.TRADING_DISABLED
    )


def test_platform_halt_is_rejected() -> None:
    validator = OrderEligibilityValidator()

    result = validator.validate(
        intent=make_intent(),
        context=OrderEligibilityContext(
            platform_halted=True
        ),
    )

    assert (
        result.reason
        is OrderEligibilityReason.PLATFORM_HALTED
    )


def test_exactly_0920_is_allowed() -> None:
    validator = OrderEligibilityValidator()

    result = validator.validate(
        intent=make_intent(
            created_at=datetime(
                2026,
                8,
                7,
                9,
                20,
                0,
            )
        ),
        context=OrderEligibilityContext(),
    )

    assert result.eligible is True


def test_before_0920_is_rejected() -> None:
    validator = OrderEligibilityValidator()

    result = validator.validate(
        intent=make_intent(
            created_at=datetime(
                2026,
                8,
                7,
                9,
                19,
                59,
            )
        ),
        context=OrderEligibilityContext(),
    )

    assert (
        result.reason
        is OrderEligibilityReason.BEFORE_EXECUTION_WINDOW
    )


def test_1514_59_is_allowed() -> None:
    validator = OrderEligibilityValidator()

    result = validator.validate(
        intent=make_intent(
            created_at=datetime(
                2026,
                8,
                7,
                15,
                14,
                59,
            )
        ),
        context=OrderEligibilityContext(),
    )

    assert result.eligible is True


def test_exactly_1515_is_rejected() -> None:
    validator = OrderEligibilityValidator()

    result = validator.validate(
        intent=make_intent(
            created_at=datetime(
                2026,
                8,
                7,
                15,
                15,
                0,
            )
        ),
        context=OrderEligibilityContext(),
    )

    assert (
        result.reason
        is OrderEligibilityReason.AFTER_EXECUTION_WINDOW
    )


def test_invalid_quantity_is_rejected() -> None:
    validator = OrderEligibilityValidator()

    result = validator.validate(
        intent=make_intent(
            quantity=100,
        ),
        context=OrderEligibilityContext(),
    )

    assert (
        result.reason
        is OrderEligibilityReason.INVALID_QUANTITY
    )


def test_limit_below_option_ltp_is_rejected() -> None:
    validator = OrderEligibilityValidator()

    result = validator.validate(
        intent=make_intent(
            limit_price=204.95,
        ),
        context=OrderEligibilityContext(),
    )

    assert (
        result.reason
        is OrderEligibilityReason.LIMIT_BELOW_OPTION_LTP
    )


def test_limit_equal_to_ltp_is_allowed() -> None:
    validator = OrderEligibilityValidator()

    result = validator.validate(
        intent=make_intent(
            limit_price=205.0,
        ),
        context=OrderEligibilityContext(),
    )

    assert result.eligible is True


def test_dry_run_is_allowed() -> None:
    validator = OrderEligibilityValidator()

    result = validator.validate(
        intent=make_intent(
            execution_mode=ExecutionMode.DRY_RUN,
        ),
        context=OrderEligibilityContext(),
    )

    assert result.eligible is True


def test_live_mode_is_structurally_allowed() -> None:
    validator = OrderEligibilityValidator()

    result = validator.validate(
        intent=make_intent(
            execution_mode=ExecutionMode.LIVE,
        ),
        context=OrderEligibilityContext(),
    )

    assert result.eligible is True


def test_invalid_window_configuration_rejected() -> None:
    from datetime import time

    with pytest.raises(
        ValueError,
        match="start_time must be before force_exit_time",
    ):
        OrderEligibilityValidator(
            start_time=time(15, 15),
            force_exit_time=time(9, 20),
        )