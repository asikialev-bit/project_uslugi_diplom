from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import (
    ComparabilityStatus,
    ComparisonResult,
    DataCompleteness,
    OrderScenario,
    PriceLineItem,
    ServiceOffer,
    Surcharge,
    normalize_unit,
)


def test_create_valid_service_offer_and_scenario() -> None:
    surcharge = Surcharge(
        name="Выезд за пределы города",
        amount=Decimal("500"),
        unit="фикс",
        is_mandatory=True,
        condition_description="При удалённости свыше 10 км",
    )
    offer = ServiceOffer(
        id="offer-1",
        provider_name="Исполнитель А",
        service_title="Базовая услуга",
        base_price=Decimal("100"),
        pricing_unit="кв.м",
        included_works=["этап 1", "этап 2"],
        included_components=["материалы"],
        surcharges=[surcharge],
        min_volume=Decimal("20"),
        max_volume=Decimal("500"),
    )
    scenario = OrderScenario(
        id="scen-1",
        title="Услуга 50 кв.м",
        required_works=["этап 1"],
        volume=Decimal("50"),
        pricing_unit="per_sqm",
        required_components=["материалы"],
        unit_conversions={"занятие": Decimal("2")},
    )

    assert offer.base_price == Decimal("100")
    assert offer.pricing_unit == "sqm"
    assert offer.surcharges[0].unit == "fixed"
    assert scenario.pricing_unit == "sqm"
    assert scenario.unit_conversions["session"] == Decimal("2")


def test_custom_industry_unit_is_accepted() -> None:
    offer = ServiceOffer(
        id="offer-custom",
        provider_name="Агентство",
        service_title="Ведение рекламы",
        base_price=Decimal("30000"),
        pricing_unit="месяц",
    )
    assert offer.pricing_unit == normalize_unit("месяц") == "month"


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
