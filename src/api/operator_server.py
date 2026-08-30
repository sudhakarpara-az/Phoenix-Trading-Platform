"""
Uvicorn deployment boundary for the M13 operator API.

This module may construct Uvicorn configuration/server objects,
but deliberately does not start, serve, stop, thread, fork, or
otherwise own the Phoenix application process lifecycle.

The actual deployment/process invocation remains outside the
M13 application composition graph.
"""

from __future__ import annotations

from dataclasses import dataclass

from uvicorn import Config
from uvicorn import Server

from src.api.operator_http import (
    OperatorHttpApplication,
)


_VALID_LOG_LEVELS = frozenset(
    {
        "trace",
        "debug",
        "info",
        "warning",
        "error",
        "critical",
    }
)


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorServerSettings:
    """
    Explicit deployment inputs for the operator HTTP server.

    Configuration governance may supply these values later;
    M13 does not source them from environment/config ownership.
    """

    host: str
    port: int
    log_level: str = "info"

    def __post_init__(
        self,
    ) -> None:
        if (
            type(self.host) is not str
            or not self.host.strip()
        ):
            raise TypeError(
                "host must be a non-empty str"
            )

        if (
            type(self.port) is not int
            or not 1 <= self.port <= 65535
        ):
            raise ValueError(
                "port must be an int from 1 to 65535"
            )

        if (
            type(self.log_level) is not str
            or self.log_level
            not in _VALID_LOG_LEVELS
        ):
            raise ValueError(
                "log_level must be one of "
                "trace/debug/info/warning/error/critical"
            )


def build_operator_uvicorn_server(
    *,
    app: OperatorHttpApplication,
    settings: OperatorServerSettings,
) -> Server:
    """
    Construct but do not start one single-process Uvicorn server.

    Reload and multi-worker process ownership are deliberately
    disabled for this in-memory exact-instance Phoenix graph.

    This function must never call Server.run() or Server.serve().
    """

    if not isinstance(
        app,
        OperatorHttpApplication,
    ):
        raise TypeError(
            "app must be OperatorHttpApplication"
        )

    if not isinstance(
        settings,
        OperatorServerSettings,
    ):
        raise TypeError(
            "settings must be OperatorServerSettings"
        )

    config = Config(
        app=app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
        workers=1,
    )

    return Server(
        config=config
    )


__all__ = [
    "OperatorServerSettings",
    "build_operator_uvicorn_server",
]
