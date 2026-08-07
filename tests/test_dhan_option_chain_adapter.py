from datetime import date, datetime

import pytest

from src.option_selection.dhan_option_chain_adapter import (
    DhanOptionChainAdapter,
)
from src.option_selection.option_chain_provider import (
    OptionChainRequest,
)
from src.option_selection.option_types import (
    OptionType,
)


REQUESTED_AT = datetime(
    2026,
    8,
    7,
    10,
    0,
)

EXPIRY = date(
    2026,
    8,
    13,
)


class FakeDhanClient:
    def __init__(
        self,
        *,
        expiry_response=None,
        chain_response=None,
    ) -> None:
        self.expiry_response = (
            expiry_response
            if expiry_response is not None
            else {
                "status": "success",
                "data": [
                    "2026-08-13",
                    "2026-08-20",
                ],
            }
        )

        self.chain_response = (
            chain_response
            if chain_response is not None
            else make_chain_response()
        )

        self.expiry_call = None
        self.chain_call = None

    def get_expiry_list(
        self,
        underlying_security_id,
        underlying_type,
    ):
        self.expiry_call = (
            underlying_security_id,
            underlying_type,
        )

        return self.expiry_response

    def get_option_chain(
        self,
        underlying_security_id,
        underlying_type,
        expiry_date,
    ):
        self.chain_call = (
            underlying_security_id,
            underlying_type,
            expiry_date,
        )

        return self.chain_response


def make_chain_response():
    return {
        "status": "success",
        "data": {
            "last_price": 24550.25,
            "oc": {
                "24500.000000": {
                    "ce": {
                        "security_id": 101,
                        "last_price": 125.50,
                        "top_bid_price": 125.40,
                        "top_ask_price": 125.60,
                        "volume": 10000,
                        "oi": 50000,
                        "implied_volatility": 12.5,
                        "greeks": {
                            "delta": 0.64,
                            "gamma": 0.001,
                            "theta": -4.5,
                            "vega": 6.2,
                        },
                    },
                    "pe": {
                        "security_id": 201,
                        "last_price": 119.25,
                        "top_bid_price": 119.10,
                        "top_ask_price": 119.30,
                        "volume": 8000,
                        "oi": 45000,
                        "implied_volatility": 13.0,
                        "greeks": {
                            "delta": -0.64,
                            "gamma": 0.001,
                            "theta": -4.0,
                            "vega": 6.0,
                        },
                    },
                },
            },
        },
    }


def make_request(
    option_type=OptionType.CALL,
    expiry=EXPIRY,
):
    return OptionChainRequest(
        underlying_symbol="NIFTY 50",
        option_type=option_type,
        reference_price=24500.0,
        requested_at=REQUESTED_AT,
        expiry=expiry,
    )


def test_provider_name() -> None:
    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient()
    )

    assert adapter.provider_name == "DHAN"


def test_call_option_is_normalized() -> None:
    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient()
    )

    snapshot = adapter.get_option_chain(
        make_request(
            OptionType.CALL
        )
    )

    assert snapshot.count() == 1

    candidate = snapshot.candidates[0]

    assert (
        candidate.contract.option_type
        is OptionType.CALL
    )

    assert candidate.contract.security_id == "101"
    assert candidate.contract.strike == 24500.0
    assert candidate.contract.expiry == EXPIRY
    assert candidate.contract.lot_size == 65

    assert candidate.ltp == 125.50
    assert candidate.delta == 0.64
    assert candidate.delta_magnitude == 0.64


def test_put_option_is_normalized() -> None:
    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient()
    )

    snapshot = adapter.get_option_chain(
        make_request(
            OptionType.PUT
        )
    )

    assert snapshot.count() == 1

    candidate = snapshot.candidates[0]

    assert (
        candidate.contract.option_type
        is OptionType.PUT
    )

    assert candidate.contract.security_id == "201"
    assert candidate.delta == -0.64
    assert candidate.delta_magnitude == 0.64


def test_snapshot_uses_dhan_underlying_ltp() -> None:
    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient()
    )

    snapshot = adapter.get_option_chain(
        make_request()
    )

    assert snapshot.reference_price == 24550.25


def test_snapshot_falls_back_to_request_price() -> None:
    response = make_chain_response()

    response["data"]["last_price"] = 0

    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient(
            chain_response=response
        )
    )

    snapshot = adapter.get_option_chain(
        make_request()
    )

    assert snapshot.reference_price == 24500.0


def test_bid_ask_volume_and_oi_are_normalized() -> None:
    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient()
    )

    candidate = adapter.get_option_chain(
        make_request()
    ).candidates[0]

    assert candidate.quote.bid == 125.40
    assert candidate.quote.ask == 125.60
    assert candidate.quote.volume == 10000
    assert candidate.quote.open_interest == 50000


def test_greeks_are_normalized() -> None:
    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient()
    )

    greeks = adapter.get_option_chain(
        make_request()
    ).candidates[0].greeks

    assert greeks.delta == 0.64
    assert greeks.gamma == 0.001
    assert greeks.theta == -4.5
    assert greeks.vega == 6.2
    assert greeks.implied_volatility == 12.5


def test_expiry_is_resolved_when_request_has_none() -> None:
    client = FakeDhanClient()

    adapter = DhanOptionChainAdapter(
        dhan_client=client
    )

    snapshot = adapter.get_option_chain(
        make_request(
            expiry=None
        )
    )

    assert snapshot.count() == 1

    assert client.expiry_call == (
        13,
        "INDEX",
    )

    assert client.chain_call == (
        13,
        "INDEX",
        "2026-08-13",
    )


def test_expired_expiry_is_ignored_when_resolving() -> None:
    client = FakeDhanClient(
        expiry_response={
            "status": "success",
            "data": [
                "2026-08-06",
                "2026-08-13",
            ],
        }
    )

    adapter = DhanOptionChainAdapter(
        dhan_client=client
    )

    snapshot = adapter.get_option_chain(
        make_request(
            expiry=None
        )
    )

    assert (
        snapshot.candidates[0]
        .contract.expiry
        == EXPIRY
    )


def test_missing_delta_skips_contract() -> None:
    response = make_chain_response()

    response["data"]["oc"][
        "24500.000000"
    ]["ce"]["greeks"]["delta"] = None

    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient(
            chain_response=response
        )
    )

    snapshot = adapter.get_option_chain(
        make_request()
    )

    assert snapshot.candidates == ()


def test_zero_ltp_skips_contract() -> None:
    response = make_chain_response()

    response["data"]["oc"][
        "24500.000000"
    ]["ce"]["last_price"] = 0

    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient(
            chain_response=response
        )
    )

    snapshot = adapter.get_option_chain(
        make_request()
    )

    assert snapshot.candidates == ()


def test_missing_security_id_skips_contract() -> None:
    response = make_chain_response()

    del response["data"]["oc"][
        "24500.000000"
    ]["ce"]["security_id"]

    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient(
            chain_response=response
        )
    )

    snapshot = adapter.get_option_chain(
        make_request()
    )

    assert snapshot.candidates == ()


def test_failed_dhan_response_raises() -> None:
    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient(
            chain_response={
                "status": "failure",
                "remarks": "test failure",
                "data": "",
            }
        )
    )

    with pytest.raises(
        RuntimeError,
        match="Dhan option chain failed",
    ):
        adapter.get_option_chain(
            make_request()
        )


def test_missing_chain_data_raises() -> None:
    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient(
            chain_response={
                "status": "success",
                "data": {
                    "last_price": 24500,
                },
            }
        )
    )

    with pytest.raises(
        RuntimeError,
        match="missing data.oc",
    ):
        adapter.get_option_chain(
            make_request()
        )


def test_no_valid_expiry_raises() -> None:
    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient(
            expiry_response={
                "status": "success",
                "data": [
                    "2026-08-01",
                    "2026-08-06",
                ],
            }
        )
    )

    with pytest.raises(
        RuntimeError,
        match="no valid option expiry",
    ):
        adapter.get_option_chain(
            make_request(
                expiry=None
            )
        )


def test_canonical_symbol_is_built() -> None:
    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient()
    )

    candidate = adapter.get_option_chain(
        make_request()
    ).candidates[0]

    assert (
        candidate.contract.symbol
        == "NIFTY50-20260813-24500-CE"
    )


def test_custom_lot_size_is_preserved() -> None:
    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient(),
        lot_size=130,
    )

    candidate = adapter.get_option_chain(
        make_request()
    ).candidates[0]

    assert candidate.contract.lot_size == 130


def test_invalid_lot_size_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="lot_size must be greater than zero",
    ):
        DhanOptionChainAdapter(
            dhan_client=FakeDhanClient(),
            lot_size=0,
        )
def test_nested_sdk_option_chain_response_is_supported() -> None:
    raw = make_chain_response()

    nested_response = {
        "status": "success",
        "remarks": "",
        "data": {
            "status": "success",
            "data": raw["data"],
        },
    }

    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhanClient(
            chain_response=nested_response
        )
    )

    snapshot = adapter.get_option_chain(
        make_request(
            OptionType.CALL
        )
    )

    assert snapshot.count() == 1

    candidate = snapshot.candidates[0]

    assert candidate.contract.security_id == "101"
    assert candidate.delta == 0.64
    assert candidate.ltp == 125.50
def test_nested_sdk_expiry_response_is_supported() -> None:
    client = FakeDhanClient(
        expiry_response={
            "status": "success",
            "remarks": "",
            "data": {
                "status": "success",
                "data": [
                    "2026-08-11",
                    "2026-08-18",
                ],
            },
        }
    )

    adapter = DhanOptionChainAdapter(
        dhan_client=client
    )

    expiry = adapter._resolve_nearest_expiry(
        date(2026, 8, 7)
    )

    assert expiry == date(
        2026,
        8,
        11,
    )