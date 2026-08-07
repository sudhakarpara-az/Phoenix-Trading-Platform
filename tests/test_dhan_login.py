import os

import pytest

from src.broker.dhan_broker import DhanBroker

pytestmark = pytest.mark.integration


def test_dhan_login_and_fund_limits() -> None:
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")

    if not client_id or not access_token:
        pytest.skip("DHAN credentials are not configured")

    broker = DhanBroker()
    client = broker.get_client()

    response = client.get_fund_limits()

    assert isinstance(response, dict)
    assert response.get("status") == "success"