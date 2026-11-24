from decimal import Decimal

from app.models import (
    ComparabilityStatus,
    DataCompleteness,
    OrderScenario,
    ServiceOffer,
    Surcharge,
)
from app.rules import check_comparability, check_completeness, evaluate_offer


def _base_scenario() -> OrderScenario:
    return OrderScenario(
        id="scen-1",
        title="Услуга 50 кв.м",
        required_works=["этап 1", "этап 2"],
        volume=Decimal("50"),
        pricing_unit="sqm",
        required_components=["материалы"],
    )


def _complete_offer() -> ServiceOffer:
    return ServiceOffer(
        id="offer-1",
        provider_name="Исполнитель А",
        service_title="Базовая услуга",
        base_price=Decimal("100"),
        pricing_unit="sqm",
        included_works=["этап 1", "этап 2"],
        included_components=["материалы"],
        min_volume=Decimal("20"),
        max_volume=Decimal("200"),
    )


def test_completeness_complete() -> None:
    assessment = check_completeness(_complete_offer(), _base_scenario())
    assert assessment.completeness == DataCompleteness.COMPLETE
    assert assessment.missing_info == []


def test_completeness_insufficient_without_price_or_unit() -> None:
    offer = _complete_offer().model_copy(update={"base_price": None, "pricing_unit": None})
    assessment = check_completeness(offer, _base_scenario())

    assert assessment.completeness == DataCompleteness.INSUFFICIENT
    assert len(assessment.missing_info) == 2


def test_completeness_partial_when_works_missing() -> None:
    offer = _complete_offer().model_copy(update={"included_works": []})
    assessment = check_completeness(offer, _base_scenario())

    assert assessment.completeness == DataCompleteness.PARTIAL
    assert len(assessment.missing_info) == 1


def test_comparability_comparable() -> None:
    assessment = check_comparability(_complete_offer(), _base_scenario())
    assert assessment.status == ComparabilityStatus.COMPARABLE
    assert assessment.differences == []


def test_comparability_not_comparable_on_volume_bounds() -> None:
    offer = _complete_offer().model_copy(update={"min_volume": Decimal("100")})
    assessment = check_comparability(offer, _base_scenario())

    assert assessment.status == ComparabilityStatus.NOT_COMPARABLE
    assert any("меньше минимального" in d for d in assessment.differences)


def test_comparability_not_comparable_on_incompatible_units() -> None:
    offer = _complete_offer().model_copy(update={"pricing_unit": "hour"})
    assessment = check_comparability(offer, _base_scenario())

    assert assessment.status == ComparabilityStatus.NOT_COMPARABLE
    assert any("Несовместимые единицы расчёта" in d for d in assessment.differences)


def test_comparability_partially_comparable_on_convertible_units() -> None:
    scenario = OrderScenario(
        id="scen-time",
        title="Консультация 2 часа",
        volume=Decimal("2"),
        pricing_unit="hour",
    )
    offer = ServiceOffer(
        id="offer-min",
        provider_name="Специалист",
        service_title="Консультация",
        base_price=Decimal("50"),
        pricing_unit="minute",
    )
    assessment = check_comparability(offer, scenario)

    assert assessment.status == ComparabilityStatus.PARTIALLY_COMPARABLE
    assert any("пересчёт единиц" in d for d in assessment.differences)


def test_comparability_partially_comparable_for_fixed_price() -> None:
    offer = _complete_offer().model_copy(update={"pricing_unit": "fixed"})
    assessment = check_comparability(offer, _base_scenario())

    assert assessment.status == ComparabilityStatus.PARTIALLY_COMPARABLE
    assert any("fixed" in d for d in assessment.differences)


def test_comparability_not_comparable_when_required_work_excluded() -> None:
    offer = _complete_offer().model_copy(
        update={"exclusions_or_limits": ["Этап 1"]}
    )
    assessment = check_comparability(offer, _base_scenario())

    assert assessment.status == ComparabilityStatus.NOT_COMPARABLE
    assert any("ограничениях" in d for d in assessment.differences)


def test_comparability_tracks_unmatched_scenario_conditions() -> None:
    scenario = _base_scenario().model_copy(update={"conditions": ["работа в выходные"]})
    offer = _complete_offer()
    evaluation = evaluate_offer(offer, scenario)

    assert evaluation.comparability.status == ComparabilityStatus.PARTIALLY_COMPARABLE
    assert any("работа в выходные" in d for d in evaluation.comparability.differences)
    assert evaluation.completeness.completeness == DataCompleteness.PARTIAL
    assert any("работа в выходные" in m for m in evaluation.completeness.missing_info)


def test_comparability_partially_comparable_on_missing_work_and_conditional_surcharge() -> None:
    offer = _complete_offer().model_copy(
        update={
            "included_works": ["этап 1"],
            "surcharges": [
                Surcharge(
                    name="Срочность",
                    amount=Decimal("500"),
                    is_mandatory=False,
                    condition_description="Выезд в день обращения",
                )
            ],
        }
    )
    assessment = check_comparability(offer, _base_scenario())

    assert assessment.status == ComparabilityStatus.PARTIALLY_COMPARABLE
    assert len(assessment.differences) == 2


def test_evaluate_offer_separates_axes() -> None:
    offer = _complete_offer().model_copy(
        update={"base_price": None, "max_volume": Decimal("30")}
    )
    evaluation = evaluate_offer(offer, _base_scenario())

    assert evaluation.completeness.completeness == DataCompleteness.INSUFFICIENT
    assert evaluation.comparability.status == ComparabilityStatus.NOT_COMPARABLE


def test_incompatible_units_do_not_emit_false_volume_bounds_error() -> None:
    scenario = OrderScenario(
        id="scen-month",
        title="Сопровождение на 1 месяц",
        volume=Decimal("1"),
        pricing_unit="month",
    )
    offer = ServiceOffer(
        id="offer-hr",
        provider_name="Подрядчик",
        service_title="Поддержка",
        base_price=Decimal("1000"),
        pricing_unit="hour",
        min_volume=Decimal("10"),
    )

    assessment = check_comparability(offer, scenario)

    assert assessment.status == ComparabilityStatus.NOT_COMPARABLE
    assert not any("меньше минимального" in d for d in assessment.differences)


def test_substring_matching_covers_offer_conditions() -> None:
    scenario = _base_scenario().model_copy(update={"conditions": ["срочно"]})
    offer = _complete_offer().model_copy(
        update={"conditions": ["срочно в день заказа"]}
    )

    evaluation = evaluate_offer(offer, scenario)

    assert evaluation.comparability.status == ComparabilityStatus.COMPARABLE
    assert evaluation.completeness.completeness == DataCompleteness.COMPLETE
