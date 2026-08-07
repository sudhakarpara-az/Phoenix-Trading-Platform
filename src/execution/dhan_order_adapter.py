"""
Dhan order execution adapter for Phoenix Trading Platform.

Translates broker-independent Phoenix OrderIntent objects
into Dhan order API calls and normalizes Dhan responses
into Phoenix execution domain models.

Automated tests for this adapter must use a fake Dhan client.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.execution.broker_execution_provider import (
    BrokerCancellationResult,
    BrokerExecutionProvider,
    BrokerOrderSnapshot,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionResult,
    OrderIntent,
)


class DhanOrderAdapter(BrokerExecutionProvider):
    """
    Dhan implementation of BrokerExecutionProvider.

    Current Phoenix order configuration:

        Exchange Segment : NSE_FNO
        Product Type     : INTRADAY
        Transaction      : BUY
        Order Type       : LIMIT
        Validity         : DAY
        AMO              : False
    """

    def __init__(
        self,
        dhan_client: Any,
        exchange_segment: str = "NSE_FNO",
        product_type: str = "INTRADAY",
        validity: str = "DAY",
    ) -> None:
        if dhan_client is None:
            raise ValueError(
                "dhan_client cannot be None"
            )

        if not exchange_segment.strip():
            raise ValueError(
                "exchange_segment cannot be empty"
            )

        if not product_type.strip():
            raise ValueError(
                "product_type cannot be empty"
            )

        if not validity.strip():
            raise ValueError(
                "validity cannot be empty"
            )

        self._dhan = dhan_client

        self._exchange_segment = (
            exchange_segment.strip()
        )

        self._product_type = (
            product_type.strip()
        )

        self._validity = (
            validity.strip()
        )

    @property
    def broker_name(self) -> str:
        return "DHAN"

    def submit_order(
        self,
        intent: OrderIntent,
    ) -> ExecutionResult:
        """
        Submit one Phoenix LIMIT BUY order to Dhan.
        """

        correlation_id = self._correlation_id(
            intent
        )

        try:
            response = self._dhan.place_order(
                security_id=(
                    intent.selected_option.security_id
                ),
                exchange_segment=(
                    self._exchange_segment
                ),
                transaction_type=(
                    intent.transaction_type.value
                ),
                quantity=intent.quantity,
                order_type=(
                    intent.order_type.value
                ),
                product_type=(
                    self._product_type
                ),
                price=intent.limit_price,
                validity=self._validity,
                correlation_id=correlation_id,
                disclosed_quantity=0,
                trigger_price=0,
                after_market_order=False,
            )

        except Exception as exc:
            return ExecutionResult(
                intent_id=intent.intent_id,
                success=False,
                status=BrokerOrderStatus.UNKNOWN,
                broker_reference=None,
                submitted_at=datetime.now(),
                message=(
                    "Dhan order submission failed: "
                    f"{exc}"
                ),
            )

        submitted_at = datetime.now()

        try:
            payload = self._unwrap_response(
                response,
                operation="order submission",
            )

        except RuntimeError as exc:
            return ExecutionResult(
                intent_id=intent.intent_id,
                success=False,
                status=BrokerOrderStatus.UNKNOWN,
                broker_reference=None,
                submitted_at=submitted_at,
                message=str(exc),
            )

        order_id = self._read_value(
            payload,
            "orderId",
            "order_id",
        )

        raw_status = self._read_value(
            payload,
            "orderStatus",
            "order_status",
        )

        status = self._map_status(
            raw_status
        )

        if order_id is None:
            return ExecutionResult(
                intent_id=intent.intent_id,
                success=False,
                status=status,
                broker_reference=None,
                submitted_at=submitted_at,
                message=(
                    "Dhan order response missing order ID"
                ),
            )

        reference = BrokerOrderReference(
            broker_name=self.broker_name,
            order_id=str(order_id),
        )

        success = status not in {
            BrokerOrderStatus.REJECTED,
            BrokerOrderStatus.CANCELLED,
            BrokerOrderStatus.UNKNOWN,
        }

        message = None

        if not success:
            message = (
                self._extract_error_message(
                    payload
                )
                or (
                    "Dhan order was not accepted "
                    f"with status {status.value}"
                )
            )

        return ExecutionResult(
            intent_id=intent.intent_id,
            success=success,
            status=status,
            broker_reference=(
                reference
                if success
                else None
            ),
            submitted_at=submitted_at,
            message=message,
        )

    def cancel_order(
        self,
        broker_reference: BrokerOrderReference,
    ) -> BrokerCancellationResult:
        """
        Cancel one pending Dhan order.
        """

        self._validate_reference(
            broker_reference
        )

        try:
            response = self._dhan.cancel_order(
                order_id=broker_reference.order_id
            )

            payload = self._unwrap_response(
                response,
                operation="order cancellation",
            )

            raw_status = self._read_value(
                payload,
                "orderStatus",
                "order_status",
            )

            status = self._map_status(
                raw_status
            )

            success = (
                status
                is BrokerOrderStatus.CANCELLED
            )

            return BrokerCancellationResult(
                broker_reference=broker_reference,
                success=success,
                status=status,
                cancelled_at=datetime.now(),
                message=(
                    None
                    if success
                    else (
                        self._extract_error_message(
                            payload
                        )
                        or (
                            "Dhan cancellation did not "
                            "return CANCELLED status"
                        )
                    )
                ),
            )

        except Exception as exc:
            return BrokerCancellationResult(
                broker_reference=broker_reference,
                success=False,
                status=BrokerOrderStatus.UNKNOWN,
                cancelled_at=datetime.now(),
                message=(
                    "Dhan order cancellation failed: "
                    f"{exc}"
                ),
            )

    def get_order_status(
        self,
        broker_reference: BrokerOrderReference,
    ) -> BrokerOrderSnapshot:
        """
        Fetch and normalize current Dhan order state.
        """

        self._validate_reference(
            broker_reference
        )

        response = self._dhan.get_order_by_id(
            order_id=broker_reference.order_id
        )

        payload = self._unwrap_response(
            response,
            operation="order status",
        )

        raw_status = self._read_value(
            payload,
            "orderStatus",
            "order_status",
        )

        status = self._map_status(
            raw_status
        )

        quantity = self._to_int(
            self._read_value(
                payload,
                "quantity",
            ),
            default=0,
        )

        filled_quantity = self._to_int(
            self._read_value(
                payload,
                "filledQty",
                "filled_quantity",
                "tradedQty",
            ),
            default=0,
        )

        average_price = self._to_positive_float(
            self._read_value(
                payload,
                "averageTradedPrice",
                "average_price",
                "avgTradedPrice",
            )
        )

        updated_at = self._parse_datetime(
            self._read_value(
                payload,
                "updateTime",
                "updated_at",
                "exchangeTime",
            )
        )

        if updated_at is None:
            updated_at = datetime.now()

        message = self._extract_error_message(
            payload
        )

        return BrokerOrderSnapshot(
            broker_reference=broker_reference,
            status=status,
            quantity=quantity,
            filled_quantity=filled_quantity,
            average_price=average_price,
            updated_at=updated_at,
            message=message,
        )

    def _validate_reference(
        self,
        reference: BrokerOrderReference,
    ) -> None:
        if (
            reference.broker_name.upper()
            != self.broker_name
        ):
            raise ValueError(
                "broker reference does not belong to DHAN"
            )

    @staticmethod
    def _correlation_id(
        intent: OrderIntent,
    ) -> str:
        """
        Dhan correlationId has a maximum length of 30 characters.

        Phoenix uses the order-intent identifier where possible.
        """

        value = intent.intent_id.value

        return value[:30]

    @staticmethod
    def _unwrap_response(
        response: Any,
        operation: str,
    ) -> dict:
        """
        Normalize raw REST and SDK-wrapped Dhan responses.

        Supports:

            {"orderId": "...", ...}

        and SDK wrappers such as:

            {
                "status": "success",
                "data": {
                    "orderId": "...",
                    ...
                }
            }

        as well as one additional nested successful envelope.
        """

        if not isinstance(
            response,
            dict,
        ):
            raise RuntimeError(
                f"Dhan {operation} returned invalid response"
            )

        current: Any = response

        for _ in range(4):
            if not isinstance(
                current,
                dict,
            ):
                raise RuntimeError(
                    f"Dhan {operation} returned invalid payload"
                )

            status = current.get(
                "status"
            )

            if (
                status is not None
                and str(status).lower()
                not in {
                    "success",
                    "successful",
                }
            ):
                message = (
                    DhanOrderAdapter
                    ._extract_error_message(
                        current
                    )
                    or str(
                        current.get(
                            "remarks"
                        )
                    )
                )

                raise RuntimeError(
                    f"Dhan {operation} failed: "
                    f"{message}"
                )

            if "data" not in current:
                return current

            data = current["data"]

            if isinstance(
                data,
                dict,
            ):
                current = data
                continue

            raise RuntimeError(
                f"Dhan {operation} returned invalid data"
            )

        raise RuntimeError(
            f"Dhan {operation} response exceeded "
            "supported wrapper depth"
        )

    @staticmethod
    def _read_value(
        payload: dict,
        *names: str,
    ) -> Any:
        for name in names:
            if name in payload:
                return payload[name]

        return None

    @staticmethod
    def _map_status(
        value: Any,
    ) -> BrokerOrderStatus:
        if value is None:
            return BrokerOrderStatus.UNKNOWN

        normalized = (
            str(value)
            .strip()
            .upper()
        )

        mapping = {
            "TRANSIT": (
                BrokerOrderStatus.PENDING
            ),
            "PENDING": (
                BrokerOrderStatus.PENDING
            ),
            "OPEN": (
                BrokerOrderStatus.OPEN
            ),
            "PART_TRADED": (
                BrokerOrderStatus.PARTIALLY_FILLED
            ),
            "PARTIALLY_FILLED": (
                BrokerOrderStatus.PARTIALLY_FILLED
            ),
            "TRADED": (
                BrokerOrderStatus.FILLED
            ),
            "FILLED": (
                BrokerOrderStatus.FILLED
            ),
            "REJECTED": (
                BrokerOrderStatus.REJECTED
            ),
            "CANCELLED": (
                BrokerOrderStatus.CANCELLED
            ),
            "CANCELED": (
                BrokerOrderStatus.CANCELLED
            ),
            "EXPIRED": (
                BrokerOrderStatus.CANCELLED
            ),
        }

        return mapping.get(
            normalized,
            BrokerOrderStatus.UNKNOWN,
        )

    @staticmethod
    def _extract_error_message(
        payload: dict,
    ) -> str | None:
        for key in (
            "omsErrorDescription",
            "errorMessage",
            "error_message",
            "message",
            "remarks",
        ):
            value = payload.get(
                key
            )

            if (
                value is not None
                and str(value).strip()
            ):
                return str(value).strip()

        return None

    @staticmethod
    def _to_int(
        value: Any,
        default: int,
    ) -> int:
        try:
            return int(
                float(value)
            )
        except (
            TypeError,
            ValueError,
        ):
            return default

    @staticmethod
    def _to_positive_float(
        value: Any,
    ) -> float | None:
        try:
            result = float(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

        if result <= 0:
            return None

        return result

    @staticmethod
    def _parse_datetime(
        value: Any,
    ) -> datetime | None:
        if value is None:
            return None

        if isinstance(
            value,
            datetime,
        ):
            return value

        text = str(value).strip()

        formats = (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
        )

        for fmt in formats:
            try:
                return datetime.strptime(
                    text,
                    fmt,
                )

            except ValueError:
                continue

        return None