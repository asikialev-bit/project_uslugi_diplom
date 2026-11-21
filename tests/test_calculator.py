from decimal import Decimal

from app.calculator import calculate_comparison, compare_offers
from app.models import (
    ComparabilityStatus,
    DataCompleteness,
    OrderScenario,
    PricingUnit,
    ServiceOffer,
    Surcharge,
)


def _scenario() -> OrderScenario:
    return OrderScenario(
        id="scen-1",
        title="Уборка офиса 50 кв.м",
        required_works=["мытьё полов", "протирка пыли"],
        volume=Decimal("50"),
        pricing_unit=PricingUnit.PER_SQM,
        required_components=["моющие средства"],
    )


def _offer(offer_id: str = "offer-1", provider: str = "Исполнитель А") -> ServiceOffer:
    return ServiceOffer(
        id=offer_id,
        provider_name=provider,
        service_title="Уборка офиса",
        base_price=Decimal("100"),
        pricing_unit=PricingUnit.PER_SQM,
        included_works=["мытьё полов", "протирка пыли"],
        included_components=["моющие средства"],
    )


def test_calculate_per_sqm_with_mandatory_surcharges() -> None:
    offer = _offer().model_copy(
        update={
            "surcharges": [
                Surcharge(
                    name="Выезд",
                    amount=Decimal("500"),
                    unit=PricingUnit.FIXED,
                    is_mandatory=True,
                ),
                Surcharge(
                    name="Дезинфекция",
                    amount=Decimal("10"),
                    unit=PricingUnit.PER_SQM,
                    is_mandatory=True,
                ),
                Surcharge(
                    name="Срочность",
                    amount=Decimal("1000"),
                    unit=PricingUnit.FIXED,
                    is_mandatory=False,
                    condition_description="В день обращения",
                ),
            ]
        }
    )

    result = calculate_comparison(offer, _scenario())

    # Необязательная доплата делает статус partially_comparable, но в сумму не входит
    assert result.status == ComparabilityStatus.PARTIALLY_COMPARABLE
    assert result.completeness == DataCompleteness.COMPLETE
    # 50 * 100 + 500 + 50 * 10 = 6000
    assert result.total_estimated_price == Decimal("6000")
    assert len(result.price_breakdown) == 3


def test_calculate_fixed_price_offer() -> None:
    offer = _offer().model_copy(
        update={
            "base_price": Decimal("4500"),
            "pricing_unit": PricingUnit.FIXED,
        }
    )

    result = calculate_comparison(offer, _scenario())

    assert result.status == ComparabilityStatus.PARTIALLY_COMPARABLE
    assert result.total_estimated_price == Decimal("4500")
    assert len(result.price_breakdown) == 1


def test_not_comparable_still_collects_missing_info_and_surcharge_issues() -> None:
    # Несовместимая единица (not_comparable), при этом нет состава работ (partial)
    # и есть обязательная доплата в несовместимой единице.
    offer = _offer().model_copy(
        update={
            "pricing_unit": PricingUnit.PER_HOUR,
            "included_works": [],
            "surcharges": [
                Surcharge(
                    name="Доп. позиция",
                    amount=Decimal("200"),
                    unit=PricingUnit.PER_UNIT,
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
        update={"base_price": Decimal("3000"), "pricing_unit": PricingUnit.FIXED}
    )
    not_comparable_offer = _offer("o4", "Неподходящий").model_copy(
        update={"pricing_unit": PricingUnit.PER_HOUR}
    )

    results = compare_offers(
        [not_comparable_offer, expensive_comparable, partial_offer, cheap_comparable],
        _scenario(),
    )

    assert [r.offer_id for r in results] == ["o2", "o1", "o3", "o4"]
