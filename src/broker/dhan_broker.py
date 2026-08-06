"""
Dhan Broker
Phoenix Trading Platform
"""

import os

from dotenv import load_dotenv
from dhanhq import DhanContext, dhanhq

load_dotenv()


class DhanBroker:
    """
    Handles authentication with Dhan API.
    """

    def __init__(self):

        self.client_id = os.getenv("DHAN_CLIENT_ID")
        self.access_token = os.getenv("DHAN_ACCESS_TOKEN")

        if not self.client_id:
            raise ValueError("DHAN_CLIENT_ID not found in .env")

        if not self.access_token:
            raise ValueError("DHAN_ACCESS_TOKEN not found in .env")

        self.context = DhanContext(
            self.client_id,
            self.access_token,
        )

        self.client = dhanhq(self.context)

    def get_client(self):
        return self.client

    def is_connected(self):
        return self.client is not None