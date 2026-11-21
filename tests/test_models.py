from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import (
    ComparabilityStatus,
    ComparisonResult,
    DataCompleteness,
    OrderScenario,
    PriceLineItem,
    PricingUnit,
    ServiceOffer,
    Surcharge,
)


def test_create_valid_service_offer_and_scenario() -> None:
    surcharge = Surcharge(
        name="Выезд за пределы города",
        amount=Decimal("500"),
        unit=PricingUnit.FIXED,
        is_mandatory=True,
        condition_description="При удалённости свыше 10 км",
    )
    offer = ServiceOffer(
        id="offer-1",
        provider_name="Исполнитель А",
        service_title="Базовая уборка офиса",
        base_price=Decimal("100"),
        pricing_unit=PricingUnit.PER_SQM,
        included_works=["мытьё полов", "протирка пыли"],
        included_components=["моющие средства"],
        surcharges=[surcharge],
        min_volume=Decimal("20"),
        max_volume=Decimal("500"),
    )
    scenario = OrderScenario(
        id="scen-1",
        title="Уборка офиса 50 кв.м",
        required_works=["мытьё полов"],
        volume=Decimal("50"),
        pricing_unit=PricingUnit.PER_SQM,
        required_components=["моющие средства"],
    )

    assert offer.base_price == Decimal("100")
    assert offer.surcharges[0].amount == Decimal("500")
    assert scenario.volume == Decimal("50")


def test_negative_price_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ServiceOffer(
            id="offer-bad",
            provider_name="Исполнитель Б",
            service_title="Тест",
            base_price=Decimal("-10"),
        )


def test_non_positive_volume_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OrderScenario(
            id="scen-bad",
            title="Нулевой объём",
            volume=Decimal("0"),
        )


def test_max_volume_less_than_min_volume_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ServiceOffer(
            id="offer-bad-bounds",
            provider_name="Исполнитель В",
            service_title="Тест",
            min_volume=Decimal("100"),
            max_volume=Decimal("50"),
        )


def test_comparison_result_serialization() -> None:
    result = ComparisonResult(
        offer_id="offer-1",
        provider_name="Исполнитель А",
        status=ComparabilityStatus.COMPARABLE,
        completeness=DataCompleteness.COMPLETE,
        total_estimated_price=Decimal("5500"),
        price_breakdown=[
            PriceLineItem(label="Базовая стоимость (50 * 100)", amount=Decimal("5000")),
            PriceLineItem(label="Выезд за пределы города", amount=Decimal("500")),
        ],
        differences=[],
        missing_info=[],
    )
    payload = result.model_dump(mode="json")

    assert payload["status"] == "comparable"
    assert payload["completeness"] == "complete"
    assert payload["total_estimated_price"] == "5500"
    assert len(payload["price_breakdown"]) == 2
