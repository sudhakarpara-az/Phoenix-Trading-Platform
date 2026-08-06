"""
Dhan Broker
Phoenix Trading Platform

Provides authenticated access to the Dhan SDK.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from dhanhq import DhanContext, dhanhq

load_dotenv()


class DhanBroker:
    """
    Dhan Broker wrapper.

    Responsibilities:
    - Load credentials
    - Create DhanContext
    - Create authenticated Dhan client
    - Expose context and client to other modules
    """

    def __init__(self) -> None:

        self._client_id = os.getenv("DHAN_CLIENT_ID")
        self._access_token = os.getenv("DHAN_ACCESS_TOKEN")

        if not self._client_id:
            raise ValueError("DHAN_CLIENT_ID not found in .env")

        if not self._access_token:
            raise ValueError("DHAN_ACCESS_TOKEN not found in .env")

        # Authenticated Dhan context
        self._context = DhanContext(
            self._client_id,
            self._access_token,
        )

        # Authenticated SDK client
        self._client = dhanhq(self._context)

    # ------------------------------------------------------------------
    # Public Getters
    # ------------------------------------------------------------------

    def get_context(self) -> DhanContext:
        """
        Return authenticated DhanContext.
        """
        return self._context

    def get_client(self):
        """
        Return authenticated Dhan client.
        """
        return self._client

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """
        Returns True if the client has been initialized.
        """
        return self._client is not None

    # ------------------------------------------------------------------
    # Information
    # ------------------------------------------------------------------

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def access_token(self) -> str:
        return self._access_token

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"DhanBroker("
            f"client_id='{self._client_id}', "
            f"connected={self.is_connected()}"
            f")"
        )