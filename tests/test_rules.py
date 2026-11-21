from decimal import Decimal

from app.models import (
    ComparabilityStatus,
    DataCompleteness,
    OrderScenario,
    PricingUnit,
    ServiceOffer,
    Surcharge,
)
from app.rules import check_comparability, check_completeness, evaluate_offer


def _base_scenario() -> OrderScenario:
    return OrderScenario(
        id="scen-1",
        title="Уборка офиса 50 кв.м",
        required_works=["мытьё полов", "протирка пыли"],
        volume=Decimal("50"),
        pricing_unit=PricingUnit.PER_SQM,
        required_components=["моющие средства"],
    )


def _complete_offer() -> ServiceOffer:
    return ServiceOffer(
        id="offer-1",
        provider_name="Исполнитель А",
        service_title="Уборка офиса",
        base_price=Decimal("100"),
        pricing_unit=PricingUnit.PER_SQM,
        included_works=["мытьё полов", "протирка пыли"],
        included_components=["моющие средства"],
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
    offer = _complete_offer().model_copy(update={"pricing_unit": PricingUnit.PER_HOUR})
    assessment = check_comparability(offer, _base_scenario())

    assert assessment.status == ComparabilityStatus.NOT_COMPARABLE
    assert any("Несовместимые единицы расчёта" in d for d in assessment.differences)


def test_comparability_partially_comparable_for_fixed_price() -> None:
    offer = _complete_offer().model_copy(update={"pricing_unit": PricingUnit.FIXED})
    assessment = check_comparability(offer, _base_scenario())

    assert assessment.status == ComparabilityStatus.PARTIALLY_COMPARABLE
    assert any("fixed" in d for d in assessment.differences)


def test_comparability_not_comparable_when_required_work_excluded() -> None:
    offer = _complete_offer().model_copy(
        update={"exclusions_or_limits": ["Мытьё полов"]}
    )
    assessment = check_comparability(offer, _base_scenario())

    assert assessment.status == ComparabilityStatus.NOT_COMPARABLE
    assert any("ограничениях" in d for d in assessment.differences)


def test_comparability_partially_comparable_on_missing_work_and_conditional_surcharge() -> None:
    offer = _complete_offer().model_copy(
        update={
            "included_works": ["мытьё полов"],
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
    # Нет цены (insufficient), но при этом объём не подходит (not_comparable)
    offer = _complete_offer().model_copy(
        update={"base_price": None, "max_volume": Decimal("30")}
    )
    evaluation = evaluate_offer(offer, _base_scenario())

    assert evaluation.completeness.completeness == DataCompleteness.INSUFFICIENT
    assert evaluation.comparability.status == ComparabilityStatus.NOT_COMPARABLE
