from decimal import Decimal

from app.calculator import calculate_comparison, compare_offers
from app.models import (
    ComparabilityStatus,
    DataCompleteness,
    OrderScenario,
    ServiceOffer,
    Surcharge,
)


def _scenario() -> OrderScenario:
    return OrderScenario(
        id="scen-1",
        title="Услуга 50 кв.м",
        required_works=["этап 1", "этап 2"],
        volume=Decimal("50"),
        pricing_unit="sqm",
        required_components=["материалы"],
    )


def _offer(offer_id: str = "offer-1", provider: str = "Исполнитель А") -> ServiceOffer:
    return ServiceOffer(
        id=offer_id,
        provider_name=provider,
        service_title="Базовая услуга",
        base_price=Decimal("100"),
        pricing_unit="sqm",
        included_works=["этап 1", "этап 2"],
        included_components=["материалы"],
    )


def test_calculate_per_sqm_with_mandatory_surcharges() -> None:
    offer = _offer().model_copy(
        update={
            "surcharges": [
                Surcharge(
                    name="Выезд",
                    amount=Decimal("500"),
                    unit="fixed",
                    is_mandatory=True,
                ),
                Surcharge(
                    name="Доп. обработка",
                    amount=Decimal("10"),
                    unit="sqm",
                    is_mandatory=True,
                ),
                Surcharge(
                    name="Срочность",
                    amount=Decimal("1000"),
                    unit="fixed",
                    is_mandatory=False,
                    condition_description="В день обращения",
                ),
            ]
        }
    )

    result = calculate_comparison(offer, _scenario())

    assert result.status == ComparabilityStatus.PARTIALLY_COMPARABLE
    assert result.completeness == DataCompleteness.COMPLETE
    assert result.total_estimated_price == Decimal("6000")
    assert len(result.price_breakdown) == 3


def test_conditional_surcharge_is_activated_by_scenario_condition() -> None:
    scenario = _scenario().model_copy(update={"conditions": ["срочно"]})
    offer = _offer().model_copy(
        update={
            "surcharges": [
                Surcharge(
                    name="Срочность",
                    amount=Decimal("1000"),
                    unit="fixed",
                    is_mandatory=False,
                    condition_description="Срочно (в день заказа)",
                )
            ]
        }
    )

    result = calculate_comparison(offer, scenario)

    assert result.status == ComparabilityStatus.COMPARABLE
    assert result.completeness == DataCompleteness.COMPLETE
    assert result.total_estimated_price == Decimal("6000")
    assert any("Доплата по условию" in item.label for item in result.price_breakdown)


def test_calculate_with_unit_conversion() -> None:
    scenario = OrderScenario(
        id="scen-conv",
        title="Обучение 2 месяца",
        volume=Decimal("2"),
        pricing_unit="month",
        unit_conversions={"session": Decimal("8")},
    )
    offer = ServiceOffer(
        id="offer-sess",
        provider_name="Преподаватель",
        service_title="Курс",
        base_price=Decimal("1000"),
        pricing_unit="занятие",
    )

    result = calculate_comparison(offer, scenario)

    assert result.status == ComparabilityStatus.PARTIALLY_COMPARABLE
    assert result.total_estimated_price == Decimal("16000")


def test_calculate_fixed_price_offer() -> None:
    offer = _offer().model_copy(
        update={
            "base_price": Decimal("4500"),
            "pricing_unit": "fixed",
        }
    )

    result = calculate_comparison(offer, _scenario())

    assert result.status == ComparabilityStatus.PARTIALLY_COMPARABLE
    assert result.total_estimated_price == Decimal("4500")
    assert len(result.price_breakdown) == 1


def test_not_comparable_still_collects_missing_info_and_surcharge_issues() -> None:
    offer = _offer().model_copy(
        update={
            "pricing_unit": "hour",
            "included_works": [],
            "surcharges": [
                Surcharge(
                    name="Доп. позиция",
                    amount=Decimal("200"),
                    unit="unit",
                    is_mandatory=True,
                )
            ],
        }
    )

    result = calculate_comparison(offer, _scenario())

    assert result.status == ComparabilityStatus.NOT_COMPARABLE
    assert result.completeness == DataCompleteness.PARTIAL
    assert result.total_estimated_price is None
    assert result.price_breakdown == []
    assert len(result.missing_info) == 1
    assert any("Доп. позиция" in d for d in result.differences)


def test_insufficient_data_returns_no_price_but_keeps_explanations() -> None:
    offer = _offer().model_copy(update={"base_price": None})

    result = calculate_comparison(offer, _scenario())

    assert result.status == ComparabilityStatus.COMPARABLE
    assert result.completeness == DataCompleteness.INSUFFICIENT
    assert result.total_estimated_price is None
    assert any("базовая цена" in m.lower() for m in result.missing_info)


def test_compare_offers_sorts_by_status_and_price() -> None:
    expensive_comparable = _offer("o1", "Дорогой").model_copy(
        update={"base_price": Decimal("150")}
    )
    cheap_comparable = _offer("o2", "Выгодный").model_copy(
        update={"base_price": Decimal("90")}
    )
    partial_offer = _offer("o3", "Фикс").model_copy(
        update={"base_price": Decimal("3000"), "pricing_unit": "fixed"}
    )
    not_comparable_offer = _offer("o4", "Неподходящий").model_copy(
        update={"pricing_unit": "hour"}
    )

    results = compare_offers(
        [not_comparable_offer, expensive_comparable, partial_offer, cheap_comparable],
        _scenario(),
    )

    assert [r.offer_id for r in results] == ["o2", "o1", "o3", "o4"]


def test_minute_to_hour_conversion_has_no_fraction_tail() -> None:
    scenario = OrderScenario(
        id="scen-min",
        title="Консультация 60 минут",
        volume=Decimal("60"),
        pricing_unit="minute",
    )
    offer = ServiceOffer(
        id="offer-hr",
        provider_name="Юрист",
        service_title="Консультация",
        base_price=Decimal("1000"),
        pricing_unit="hour",
    )

    result = calculate_comparison(offer, scenario)

    assert result.total_estimated_price == Decimal("1000")
    assert str(result.total_estimated_price) == "1000"
