from __future__ import annotations

import ast

from pathlib import Path

import pytest
from fastapi import FastAPI
from uvicorn import Server

from src.api.operator_server import (
    OperatorServerSettings,
    build_operator_uvicorn_server,
)


def test_server_settings_accept_valid_values() -> None:
    settings = OperatorServerSettings(
        host="127.0.0.1",
        port=8765,
        log_level="info",
    )

    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.log_level == "info"


@pytest.mark.parametrize(
    "host",
    (
        "",
        "   ",
        123,
        None,
    ),
)
def test_server_settings_reject_invalid_host(
    host: object,
) -> None:
    with pytest.raises(
        TypeError,
        match="host must be a non-empty str",
    ):
        OperatorServerSettings(
            host=host,  # type: ignore[arg-type]
            port=8765,
        )


@pytest.mark.parametrize(
    "port",
    (
        0,
        65536,
        -1,
        True,
    ),
)
def test_server_settings_reject_invalid_port(
    port: object,
) -> None:
    with pytest.raises(
        ValueError,
        match=(
            "port must be an int "
            "from 1 to 65535"
        ),
    ):
        OperatorServerSettings(
            host="127.0.0.1",
            port=port,  # type: ignore[arg-type]
        )


def test_server_settings_reject_invalid_log_level() -> None:
    with pytest.raises(
        ValueError,
        match="log_level must be one of",
    ):
        OperatorServerSettings(
            host="127.0.0.1",
            port=8765,
            log_level="verbose",
        )


def test_server_factory_preserves_exact_app() -> None:
    app = FastAPI()

    settings = OperatorServerSettings(
        host="127.0.0.1",
        port=8765,
        log_level="warning",
    )

    server = build_operator_uvicorn_server(
        app=app,
        settings=settings,
    )

    assert isinstance(
        server,
        Server,
    )

    assert server.config.app is app

    assert (
        server.config.host
        == "127.0.0.1"
    )

    assert server.config.port == 8765

    assert (
        server.config.log_level
        == "warning"
    )

    assert server.config.reload is False
    assert server.config.workers == 1

    assert server.started is False


def test_server_factory_is_passive() -> None:
    app = FastAPI()

    settings = OperatorServerSettings(
        host="127.0.0.1",
        port=8765,
    )

    server = build_operator_uvicorn_server(
        app=app,
        settings=settings,
    )

    assert server.started is False
    assert server.should_exit is False

    # Construction must not load/bind/start the server.
    assert server.config.loaded is False


def test_server_module_contains_no_process_start() -> None:
    path = Path(
        "src/api/operator_server.py"
    )

    text = path.read_text(
        encoding="utf-8-sig"
    )

    tree = ast.parse(
        text,
        filename=str(path),
    )

    forbidden_modules = {
        "asyncio",
        "threading",
        "multiprocessing",
        "subprocess",
    }

    forbidden_attribute_calls = {
        "run",
        "serve",
        "register_component",
        "exit_and_stop",
        "resume",
    }

    forbidden_name_calls = {
        "start_composed_runtime",
        "StartupManager",
        "ShutdownManager",
    }

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            ast.Import,
        ):
            for alias in node.names:
                root = alias.name.split(
                    ".",
                    1,
                )[0]

                assert (
                    root
                    not in forbidden_modules
                )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            if node.module is None:
                continue

            root = node.module.split(
                ".",
                1,
            )[0]

            assert (
                root
                not in forbidden_modules
            )

        elif isinstance(
            node,
            ast.Call,
        ):
            target = node.func

            if isinstance(
                target,
                ast.Attribute,
            ):
                assert (
                    target.attr
                    not in forbidden_attribute_calls
                )

            elif isinstance(
                target,
                ast.Name,
            ):
                assert (
                    target.id
                    not in forbidden_name_calls
                )



def test_server_factory_rejects_wrong_inputs() -> None:
    settings = OperatorServerSettings(
        host="127.0.0.1",
        port=8765,
    )

    with pytest.raises(
        TypeError,
        match="app must be OperatorHttpApplication",
    ):
        build_operator_uvicorn_server(
            app=object(),  # type: ignore[arg-type]
            settings=settings,
        )

    with pytest.raises(
        TypeError,
        match="settings must be OperatorServerSettings",
    ):
        build_operator_uvicorn_server(
            app=FastAPI(),
            settings=object(),  # type: ignore[arg-type]
        )
