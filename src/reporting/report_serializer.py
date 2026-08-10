"""
Deterministic M12 JSON serialization.

Only immutable M12 reporting read models cross this boundary.
"""

from __future__ import annotations

from dataclasses import (
    asdict,
    is_dataclass,
)
from datetime import (
    date,
    datetime,
)
from enum import Enum
import json
from typing import Any

from src.reporting.reporting_types import (
    DailyTradeReport,
    RuntimeTradeReport,
)


class ReportSerializationError(
    ValueError,
):
    """
    Reporting value cannot be serialized safely.
    """


class ReportJsonSerializer:
    """
    Deterministic JSON representation of M12 reports.
    """

    def to_dict(
        self,
        report: RuntimeTradeReport | DailyTradeReport,
    ) -> dict[
        str,
        Any,
    ]:
        if not isinstance(
            report,
            (
                RuntimeTradeReport,
                DailyTradeReport,
            ),
        ):
            raise TypeError(
                "report must be RuntimeTradeReport "
                "or DailyTradeReport"
            )

        converted = self._convert(
            report
        )

        if not isinstance(
            converted,
            dict,
        ):
            raise ReportSerializationError(
                "report did not serialize to mapping"
            )

        return converted

    def to_json(
        self,
        report: RuntimeTradeReport | DailyTradeReport,
        *,
        indent: int | None = None,
    ) -> str:
        if (
            indent is not None
            and (
                type(indent) is not int
                or indent < 0
            )
        ):
            raise ValueError(
                "indent must be non-negative int or None"
            )

        try:
            return json.dumps(
                self.to_dict(
                    report
                ),
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
                indent=indent,
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ReportSerializationError(
                "report JSON serialization failed: "
                f"{exc}"
            ) from exc

    @classmethod
    def _convert(
        cls,
        value: object,
    ) -> Any:
        if (
            is_dataclass(
                value
            )
            and not isinstance(
                value,
                type,
            )
        ):
            return cls._convert(
                asdict(
                    value
                )
            )

        if isinstance(
            value,
            datetime,
        ):
            return value.isoformat()

        if isinstance(
            value,
            date,
        ):
            return value.isoformat()

        if isinstance(
            value,
            Enum,
        ):
            return cls._convert(
                value.value
            )

        if isinstance(
            value,
            dict,
        ):
            converted: dict[
                str,
                Any,
            ] = {}

            for key, item in value.items():
                if not isinstance(
                    key,
                    str,
                ):
                    raise ReportSerializationError(
                        "report dictionary keys "
                        "must be strings"
                    )

                converted[key] = cls._convert(
                    item
                )

            return converted

        if isinstance(
            value,
            (
                tuple,
                list,
            ),
        ):
            return [
                cls._convert(item)
                for item in value
            ]

        if (
            value is None
            or isinstance(
                value,
                (
                    str,
                    int,
                    float,
                    bool,
                ),
            )
        ):
            return value

        raise ReportSerializationError(
            "unsupported reporting value: "
            f"{type(value).__name__}"
        )


__all__ = [
    "ReportJsonSerializer",
    "ReportSerializationError",
]
