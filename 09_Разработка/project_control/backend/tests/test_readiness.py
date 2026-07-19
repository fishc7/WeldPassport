from decimal import Decimal

from app.readiness import MetricInput, calculate_readiness


def test_calculates_weighted_readiness_for_complete_metric_set() -> None:
    result = calculate_readiness(
        [
            MetricInput(code="features", value=Decimal("0.75"), weight=40),
            MetricInput(code="tests", value=Decimal("0.80"), weight=25),
            MetricInput(code="migrations", value=Decimal("1"), weight=15),
            MetricInput(code="documentation", value=Decimal("0.50"), weight=10),
            MetricInput(code="ci", value=Decimal("1"), weight=10),
        ]
    )

    assert result.percent == Decimal("80.00")
    assert result.is_complete is True
    assert result.missing_codes == ()


def test_normalizes_weights_when_metric_is_not_applicable() -> None:
    result = calculate_readiness(
        [
            MetricInput(code="features", value=Decimal("0.50"), weight=40),
            MetricInput(code="tests", value=Decimal("1"), weight=25),
            MetricInput(code="migrations", value=None, weight=15, applicable=False),
            MetricInput(code="documentation", value=Decimal("1"), weight=10),
            MetricInput(code="ci", value=Decimal("1"), weight=10),
        ]
    )

    assert result.percent == Decimal("76.47")
    assert result.is_complete is True


def test_reports_missing_applicable_metric_without_treating_it_as_zero() -> None:
    result = calculate_readiness(
        [
            MetricInput(code="features", value=Decimal("1"), weight=40),
            MetricInput(code="tests", value=None, weight=25),
        ]
    )

    assert result.percent == Decimal("100.00")
    assert result.is_complete is False
    assert result.missing_codes == ("tests",)
