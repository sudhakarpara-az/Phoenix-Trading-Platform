"""
Phoenix M08 startup recovery and broker reconciliation.

Responsibilities:
    - discover interrupted runtime state
    - identify unresolved orders
    - identify persisted open exposure
    - query broker truth
    - fail closed on uncertainty
    - restore only confirmed state
    - complete orchestrator recovery only after all checks pass

This module does not contain Dhan API code.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import (
    TYPE_CHECKING,
    Protocol,
)

if TYPE_CHECKING:
    from src.database.schema import (
        OrderRecord,
        PositionRecord,
        RuntimeSessionRecord,
    )

from src.runtime.recovery_types import (
    BrokerRecoveryOrderState,
    BrokerRecoveryProvider,
    RecoveryIssue,
    RecoveryIssueCode,
    RecoveryStateRestorer,
    StartupRecoveryPlan,
    StartupRecoveryResult,
)
from src.runtime.runtime_orchestrator import (
    RuntimeTransitionError,
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeFailureCode,
    RuntimeState,
)


class RecoveryRuntimeRepository(Protocol):
    def latest_for_trading_date(
        self,
        trading_date: date,
    ) -> RuntimeSessionRecord | None:
        ...


class RecoveryOrderRepository(Protocol):
    def list_open_orders(
        self,
        runtime_id: str,
    ) -> tuple[
        OrderRecord,
        ...,
    ]:
        ...


class RecoveryPositionRepository(Protocol):
    def list_open_positions(
        self,
        runtime_id: str,
    ) -> tuple[
        PositionRecord,
        ...,
    ]:
        ...


class StartupRecoveryService:
    """
    Reconciles persisted Phoenix state against broker truth.
    """

    _CLEAN_TERMINAL_RUNTIME_STATES = {
        "STOPPED",
    }

    def __init__(
        self,
        *,
        runtime_repository:
            RecoveryRuntimeRepository,
        order_repository:
            RecoveryOrderRepository,
        position_repository:
            RecoveryPositionRepository,
        broker_provider:
            BrokerRecoveryProvider,
        state_restorer:
            RecoveryStateRestorer,
    ) -> None:
        self._runtime_repository = (
            runtime_repository
        )

        self._order_repository = (
            order_repository
        )

        self._position_repository = (
            position_repository
        )

        self._broker_provider = (
            broker_provider
        )

        self._state_restorer = (
            state_restorer
        )

    # ========================================================
    # Discovery
    # ========================================================

    @property
    def broker_provider(
        self,
    ) -> BrokerRecoveryProvider:
        """
        Return the exact broker-truth provider owned by recovery.
        """

        return self._broker_provider


    @property
    def state_restorer(
        self,
    ) -> RecoveryStateRestorer:
        """
        Return the exact state-restorer boundary owned by recovery.
        """

        return self._state_restorer

    def build_plan(
        self,
        *,
        trading_date: date,
    ) -> StartupRecoveryPlan:
        """
        Inspect latest persisted Phoenix runtime.

        Recovery is required when:
            - previous runtime did not finish STOPPED
            - unresolved broker orders remain
            - persisted open exposure remains
        """

        runtime = (
            self._runtime_repository
            .latest_for_trading_date(
                trading_date
            )
        )

        if runtime is None:
            return StartupRecoveryPlan(
                source_runtime_id=None,
                persisted_runtime_state=None,
                unresolved_order_count=0,
                open_position_count=0,
                recovery_required=False,
            )

        orders = (
            self._order_repository
            .list_open_orders(
                runtime.runtime_id
            )
        )

        positions = (
            self._position_repository
            .list_open_positions(
                runtime.runtime_id
            )
        )

        interrupted = (
            runtime.state
            not in self._CLEAN_TERMINAL_RUNTIME_STATES
        )

        recovery_required = (
            interrupted
            or bool(orders)
            or bool(positions)
        )

        return StartupRecoveryPlan(
            source_runtime_id=(
                runtime.runtime_id
            ),
            persisted_runtime_state=(
                runtime.state
            ),
            unresolved_order_count=len(
                orders
            ),
            open_position_count=len(
                positions
            ),
            recovery_required=(
                recovery_required
            ),
        )

    # ========================================================
    # Recovery
    # ========================================================

    def recover(
        self,
        *,
        orchestrator:
            TradingRuntimeOrchestrator,
        source_runtime_id: str,
        checked_at: datetime,
    ) -> StartupRecoveryResult:
        """
        Reconcile one persisted runtime.

        The orchestrator MUST already be RECOVERING.
        """

        if (
            orchestrator.state
            is not RuntimeState.RECOVERING
        ):
            raise RuntimeTransitionError(
                "startup recovery requires "
                "RECOVERING runtime state"
            )

        issues: list[
            RecoveryIssue
        ] = []

        recovered_orders = 0
        recovered_positions = 0

        orders = (
            self._order_repository
            .list_open_orders(
                source_runtime_id
            )
        )


        # ----------------------------------------------------
        # Orders
        # ----------------------------------------------------

        for order in orders:
            broker_order_id = (
                order.broker_order_id
            )

            if not broker_order_id:
                issues.append(
                    RecoveryIssue(
                        code=(
                            RecoveryIssueCode
                            .ORDER_MISSING_BROKER_ID
                        ),
                        entity_type="ORDER",
                        entity_id=(
                            order.order_intent_id
                        ),
                        message=(
                            "persisted unresolved order "
                            "has no broker order id"
                        ),
                    )
                )

                continue

            try:
                snapshot = (
                    self._broker_provider
                    .get_order_snapshot(
                        broker_order_id=(
                            broker_order_id
                        ),
                        checked_at=checked_at,
                    )
                )

            except Exception as exc:
                issues.append(
                    RecoveryIssue(
                        code=(
                            RecoveryIssueCode
                            .BROKER_QUERY_FAILED
                        ),
                        entity_type="ORDER",
                        entity_id=(
                            order.order_intent_id
                        ),
                        message=(
                            "broker order reconciliation "
                            f"failed: {exc}"
                        ),
                    )
                )

                continue

            if (
                snapshot.state
                is BrokerRecoveryOrderState.NOT_FOUND
            ):
                issues.append(
                    RecoveryIssue(
                        code=(
                            RecoveryIssueCode
                            .ORDER_NOT_FOUND
                        ),
                        entity_type="ORDER",
                        entity_id=(
                            order.order_intent_id
                        ),
                        message=(
                            "broker could not find "
                            "persisted order"
                        ),
                    )
                )

                continue

            if (
                snapshot.state
                is BrokerRecoveryOrderState.UNKNOWN
            ):
                issues.append(
                    RecoveryIssue(
                        code=(
                            RecoveryIssueCode
                            .ORDER_STATE_UNKNOWN
                        ),
                        entity_type="ORDER",
                        entity_id=(
                            order.order_intent_id
                        ),
                        message=(
                            "broker order state is unknown"
                        ),
                    )
                )

                continue

            try:
                self._state_restorer.restore_order(
                    persisted_order=order,
                    broker_snapshot=snapshot,
                )

                recovered_orders += 1

            except Exception as exc:
                issues.append(
                    RecoveryIssue(
                        code=(
                            RecoveryIssueCode
                            .RESTORE_FAILED
                        ),
                        entity_type="ORDER",
                        entity_id=(
                            order.order_intent_id
                        ),
                        message=(
                            "order state restore failed: "
                            f"{exc}"
                        ),
                    )
                )

        # ----------------------------------------------------
        # Positions
        #
        # Broker positions are net positions per security id.
        # Phoenix may have multiple logical positions pointing
        # to the same option contract, so compare AGGREGATE
        # persisted exposure to broker net exposure first.
        # ----------------------------------------------------

        # Order restoration may durably change PositionRecord exposure
        # (especially a recovered SELL fill). Reload after every
        # unresolved order has been restored so broker-position
        # reconciliation uses current durable truth rather than
        # a stale pre-order snapshot.
        positions = (
            self._position_repository
            .list_open_positions(
                source_runtime_id
            )
        )

        positions_by_security = defaultdict(
            list
        )

        for position in positions:
            positions_by_security[
                position.security_id
            ].append(
                position
            )

        for (
            security_id,
            security_positions,
        ) in positions_by_security.items():

            expected_quantity = sum(
                position.open_quantity
                for position
                in security_positions
            )

            try:
                broker_position = (
                    self._broker_provider
                    .get_position_snapshot(
                        security_id=security_id,
                        checked_at=checked_at,
                    )
                )

            except Exception as exc:
                for position in (
                    security_positions
                ):
                    issues.append(
                        RecoveryIssue(
                            code=(
                                RecoveryIssueCode
                                .BROKER_QUERY_FAILED
                            ),
                            entity_type="POSITION",
                            entity_id=(
                                position.position_id
                            ),
                            message=(
                                "broker position reconciliation "
                                f"failed: {exc}"
                            ),
                        )
                    )

                continue

            if (
                broker_position.net_quantity
                != expected_quantity
            ):
                for position in (
                    security_positions
                ):
                    issues.append(
                        RecoveryIssue(
                            code=(
                                RecoveryIssueCode
                                .POSITION_QUANTITY_MISMATCH
                            ),
                            entity_type="POSITION",
                            entity_id=(
                                position.position_id
                            ),
                            message=(
                                "persisted aggregate quantity "
                                f"{expected_quantity} does not "
                                "match broker net quantity "
                                f"{broker_position.net_quantity}"
                            ),
                        )
                    )

                continue

            for position in security_positions:
                try:
                    (
                        self._state_restorer
                        .restore_position(
                            persisted_position=(
                                position
                            ),
                            broker_snapshot=(
                                broker_position
                            ),
                        )
                    )

                    recovered_positions += 1

                except Exception as exc:
                    issues.append(
                        RecoveryIssue(
                            code=(
                                RecoveryIssueCode
                                .RESTORE_FAILED
                            ),
                            entity_type="POSITION",
                            entity_id=(
                                position.position_id
                            ),
                            message=(
                                "position state restore failed: "
                                f"{exc}"
                            ),
                        )
                    )

        # ----------------------------------------------------
        # Recovery gate
        # ----------------------------------------------------

        if issues:
            orchestrator.fail(
                code=(
                    RuntimeFailureCode
                    .RECOVERY_FAILED
                ),
                message=(
                    "startup recovery could not "
                    f"reconcile {len(issues)} item(s)"
                ),
                failed_at=checked_at,
                component="startup-recovery",
                recoverable=True,
            )

            return StartupRecoveryResult(
                source_runtime_id=(
                    source_runtime_id
                ),
                recovered_orders=(
                    recovered_orders
                ),
                recovered_positions=(
                    recovered_positions
                ),
                issues=tuple(
                    issues
                ),
                completed=False,
            )

        orchestrator.complete_recovery(
            completed_at=checked_at
        )

        return StartupRecoveryResult(
            source_runtime_id=(
                source_runtime_id
            ),
            recovered_orders=(
                recovered_orders
            ),
            recovered_positions=(
                recovered_positions
            ),
            issues=(),
            completed=True,
        )
