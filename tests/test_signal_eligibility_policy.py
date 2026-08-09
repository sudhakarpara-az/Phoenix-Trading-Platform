from datetime import date, datetime, time

import pytest

from src.signals.eligibility_policy import (
    EligibilityContext,
    EligibilityDecision,
    EligibilityReason,
    SignalEligibilityPolicy,
)
from src.strategy.strategy_types import (
    KSLevelName,
    LevelEvent,
    LevelEventType,
    StrategySessionState,
)


TRADING_DATE = date(2026, 8, 7)

INSTRUMENT_SECURITY_ID = "12345"
INSTRUMENT_SYMBOL = "NIFTY-24550-CE"


def make_event(
    level: KSLevelName = KSLevelName.K5,
    hour: int = 10,
    minute: int = 0,
    day: int = 7,
) -> LevelEvent:
    return LevelEvent(
        trading_date=date(
            2026,
            8,
            day,
        ),
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        instrument_symbol=INSTRUMENT_SYMBOL,
        level=level,
        event_type=LevelEventType.CROSSED_UP,
        level_price=24500.0,
        market_price=24501.0,
        timestamp=datetime(
            2026,
            8,
            day,
            hour,
            minute,
        ),
    )


def make_context(
    trading_date: date = TRADING_DATE,
    session_state: StrategySessionState = (
        StrategySessionState.MONITORING
    ),
    trading_enabled: bool = True,
    platform_halted: bool = False,
) -> EligibilityContext:
    return EligibilityContext(
        trading_date=trading_date,
        session_state=session_state,
        trading_enabled=trading_enabled,
        platform_halted=platform_halted,
    )


def test_valid_k5_event_is_eligible() -> None:
    policy = SignalEligibilityPolicy()

    decision = policy.evaluate(
        make_event(KSLevelName.K5),
        make_context(),
    )

    assert decision.eligible is True
    assert decision.reason is EligibilityReason.ELIGIBLE


def test_valid_k6_event_is_eligible() -> None:
    policy = SignalEligibilityPolicy()

    decision = policy.evaluate(
        make_event(KSLevelName.K6),
        make_context(),
    )

    assert decision.eligible is True


def test_valid_k7_event_is_eligible() -> None:
    policy = SignalEligibilityPolicy()

    decision = policy.evaluate(
        make_event(KSLevelName.K7),
        make_context(),
    )

    assert decision.eligible is True


def test_k3_is_not_entry_eligible() -> None:
    policy = SignalEligibilityPolicy()

    decision = policy.evaluate(
        make_event(KSLevelName.K3),
        make_context(),
    )

    assert decision.eligible is False

    assert (
        decision.reason
        is EligibilityReason.INVALID_LEVEL
    )


def test_event_before_920_is_rejected() -> None:
    policy = SignalEligibilityPolicy()

    decision = policy.evaluate(
        make_event(
            KSLevelName.K5,
            hour=9,
            minute=19,
        ),
        make_context(),
    )

    assert decision.eligible is False

    assert (
        decision.reason
        is EligibilityReason.BEFORE_TRADING_WINDOW
    )


def test_event_at_920_is_allowed() -> None:
    policy = SignalEligibilityPolicy()

    decision = policy.evaluate(
        make_event(
            KSLevelName.K5,
            hour=9,
            minute=20,
        ),
        make_context(),
    )

    assert decision.eligible is True


def test_event_before_1515_is_allowed() -> None:
    policy = SignalEligibilityPolicy()

    decision = policy.evaluate(
        make_event(
            KSLevelName.K5,
            hour=15,
            minute=14,
        ),
        make_context(),
    )

    assert decision.eligible is True


def test_event_at_1515_is_rejected() -> None:
    policy = SignalEligibilityPolicy()

    decision = policy.evaluate(
        make_event(
            KSLevelName.K5,
            hour=15,
            minute=15,
        ),
        make_context(),
    )

    assert decision.eligible is False

    assert (
        decision.reason
        is EligibilityReason.AFTER_TRADING_WINDOW
    )


def test_strategy_not_monitoring_is_rejected() -> None:
    policy = SignalEligibilityPolicy()

    context = make_context(
        session_state=StrategySessionState.LEVELS_READY
    )

    decision = policy.evaluate(
        make_event(),
        context,
    )

    assert decision.eligible is False

    assert (
        decision.reason
        is EligibilityReason.STRATEGY_NOT_MONITORING
    )


def test_trading_disabled_is_rejected() -> None:
    policy = SignalEligibilityPolicy()

    context = make_context(
        trading_enabled=False,
    )

    decision = policy.evaluate(
        make_event(),
        context,
    )

    assert decision.eligible is False

    assert (
        decision.reason
        is EligibilityReason.TRADING_DISABLED
    )


def test_platform_halt_is_rejected() -> None:
    policy = SignalEligibilityPolicy()

    context = make_context(
        platform_halted=True,
    )

    decision = policy.evaluate(
        make_event(),
        context,
    )

    assert decision.eligible is False

    assert (
        decision.reason
        is EligibilityReason.PLATFORM_HALTED
    )


def test_wrong_trading_date_is_rejected() -> None:
    policy = SignalEligibilityPolicy()

    event = make_event(
        day=8,
    )

    decision = policy.evaluate(
        event,
        make_context(),
    )

    assert decision.eligible is False

    assert (
        decision.reason
        is EligibilityReason.WRONG_TRADING_DATE
    )


def test_invalid_time_configuration_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="trading_end must be after trading_start",
    ):
        SignalEligibilityPolicy(
            trading_start=time(15, 15),
            trading_end=time(9, 20),
        )


def test_valid_eligibility_decision_contract() -> None:
    decision = EligibilityDecision(
        eligible=True,
        reason=EligibilityReason.ELIGIBLE,
    )

    assert decision.eligible is True


def test_invalid_positive_decision_contract_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="eligible decision must use ELIGIBLE reason",
    ):
        EligibilityDecision(
            eligible=True,
            reason=EligibilityReason.INVALID_LEVEL,
        )


def test_invalid_rejected_decision_contract_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="rejected decision cannot use ELIGIBLE reason",
    ):
        EligibilityDecision(
            eligible=False,
            reason=EligibilityReason.ELIGIBLE,
        )