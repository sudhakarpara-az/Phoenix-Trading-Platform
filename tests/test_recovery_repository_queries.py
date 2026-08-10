
"""
M10 recovery repository query tests.
"""

from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyOrderRepository,
    SQLAlchemyPositionRepository,
    SQLAlchemyRuntimeSessionRepository,
    SQLAlchemySignalRepository,
)

from tests.test_database_repositories import (
    TODAY,
    make_runtime,
    order_record,
    position_record,
    runtime_record,
    seed_entry_dependencies,
    signal_record,
)


def test_open_sell_lookup_crosses_runtime_boundary():
    database, sessions = (
        make_runtime()
    )

    try:
        runtime_repo = (
            SQLAlchemyRuntimeSessionRepository(
                sessions=sessions
            )
        )

        signal_repo = (
            SQLAlchemySignalRepository(
                sessions=sessions
            )
        )

        order_repo = (
            SQLAlchemyOrderRepository(
                sessions=sessions
            )
        )

        position_repo = (
            SQLAlchemyPositionRepository(
                sessions=sessions
            )
        )

        seed_entry_dependencies(
            runtime_repo,
            signal_repo,
            order_repo,
        )

        position_repo.add(
            position_record()
        )

        sell = order_record(
            order_id=(
                "EXIT-20260810-000003"
            ),
            runtime_id=(
                "RUNTIME-001"
            ),
            signal_id=None,
            status="SUBMITTED",
            broker_order_id=(
                "BROKER-SELL-003"
            ),
        )

        sell.position_id = "POS-001"
        sell.side = "SELL"
        sell.order_type = "MARKET"
        sell.reason = "FORCE_EXIT"
        sell.execution_mode = "LIVE"
        sell.limit_price = None

        order_repo.add(
            sell
        )

        # New process/runtime exists, but recovered SELL still
        # belongs to the interrupted source runtime.
        runtime_repo.add(
            runtime_record(
                runtime_id=(
                    "RUNTIME-002"
                )
            )
        )

        matches = (
            order_repo
            .list_open_orders_for_position(
                "POS-001"
            )
        )

        assert len(matches) == 1

        assert (
            matches[0].order_intent_id
            == "EXIT-20260810-000003"
        )

        assert (
            matches[0].runtime_id
            == "RUNTIME-001"
        )

    finally:
        sessions.stop()
        database.dispose()


def test_trading_date_query_includes_terminal_orders_all_runtimes():
    database, sessions = (
        make_runtime()
    )

    try:
        runtime_repo = (
            SQLAlchemyRuntimeSessionRepository(
                sessions=sessions
            )
        )

        signal_repo = (
            SQLAlchemySignalRepository(
                sessions=sessions
            )
        )

        order_repo = (
            SQLAlchemyOrderRepository(
                sessions=sessions
            )
        )

        seed_entry_dependencies(
            runtime_repo,
            signal_repo,
            order_repo,
        )

        runtime_repo.add(
            runtime_record(
                runtime_id="RUNTIME-002"
            )
        )

        signal_repo.add(
            signal_record(
                signal_id="SIG-002",
                runtime_id="RUNTIME-002",
            )
        )

        order_repo.add(
            order_record(
                order_id=(
                    "ORD-20260810-000009"
                ),
                runtime_id="RUNTIME-002",
                signal_id="SIG-002",
                status="FILLED",
                broker_order_id=(
                    "BROKER-009"
                ),
            )
        )

        orders = (
            order_repo
            .list_by_trading_date(
                TODAY
            )
        )

        ids = {
            item.order_intent_id
            for item in orders
        }

        # Seed dependency ORD-001 is terminal FILLED and must
        # remain visible because that sequence was consumed.
        assert "ORD-001" in ids

        assert (
            "ORD-20260810-000009"
            in ids
        )

        runtimes = {
            item.runtime_id
            for item in orders
        }

        assert (
            "RUNTIME-001"
            in runtimes
        )

        assert (
            "RUNTIME-002"
            in runtimes
        )

    finally:
        sessions.stop()
        database.dispose()
