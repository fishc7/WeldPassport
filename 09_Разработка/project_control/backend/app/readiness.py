from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class MetricInput:
    code: str
    value: Decimal | None
    weight: int
    applicable: bool = True


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    percent: Decimal
    is_complete: bool
    missing_codes: tuple[str, ...]


def calculate_readiness(metrics: list[MetricInput]) -> ReadinessResult:
    available = [metric for metric in metrics if metric.applicable and metric.value is not None]
    missing = tuple(
        metric.code for metric in metrics if metric.applicable and metric.value is None
    )
    total_weight = sum(metric.weight for metric in available)
    if total_weight == 0:
        return ReadinessResult(
            percent=Decimal("0.00"),
            is_complete=not missing,
            missing_codes=missing,
        )

    weighted_value = sum(
        (metric.value or Decimal("0")) * metric.weight for metric in available
    )
    percent = (weighted_value * 100 / total_weight).quantize(Decimal("0.01"))
    return ReadinessResult(
        percent=percent,
        is_complete=not missing,
        missing_codes=missing,
    )
