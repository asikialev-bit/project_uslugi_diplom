from decimal import Decimal
from typing import List, Optional, Tuple

from app.models import (
    ComparabilityStatus,
    ComparisonResult,
    DataCompleteness,
    OrderScenario,
    PriceLineItem,
    PricingUnit,
    ServiceOffer,
)
from app.rules import evaluate_offer


def _calculate_unit_amount(
    unit_price: Decimal,
    unit: PricingUnit,
    scenario: OrderScenario,
) -> Optional[Decimal]:
    """Вычисляет сумму для ставки с учётом единицы расчёта сценария."""
    if unit == PricingUnit.FIXED:
        return unit_price
    if unit == scenario.pricing_unit:
        return unit_price * scenario.volume
    return None


def calculate_comparison(
    offer: ServiceOffer,
    scenario: OrderScenario,
) -> ComparisonResult:
    """Оценивает предложение под сценарий и при возможности рассчитывает стоимость."""
    evaluation = evaluate_offer(offer, scenario)
    differences = list(evaluation.comparability.differences)
    missing_info = list(evaluation.completeness.missing_info)

    status = evaluation.comparability.status
    completeness = evaluation.completeness.completeness

    # Проверяем совместимость единиц обязательных доплат независимо от итогового статуса,
    # чтобы пользователь видел все причины расхождений и неполноты.
    for surcharge in offer.surcharges:
        if (
            surcharge.is_mandatory
            and surcharge.unit != PricingUnit.FIXED
            and surcharge.unit != scenario.pricing_unit
        ):
            differences.append(
                f"Невозможно рассчитать обязательную доплату «{surcharge.name}»: "
                f"единица '{surcharge.unit.value}' несовместима со сценарием "
                f"'{scenario.pricing_unit.value}'"
            )

    price_breakdown: List[PriceLineItem] = []
    total_estimated_price: Optional[Decimal] = None

    can_calculate = (
        completeness != DataCompleteness.INSUFFICIENT
        and status != ComparabilityStatus.NOT_COMPARABLE
        and offer.base_price is not None
        and offer.pricing_unit is not None
    )

    if can_calculate:
        base_amount = _calculate_unit_amount(
            offer.base_price,
            offer.pricing_unit,
            scenario,
        )
        if base_amount is not None:
            if offer.pricing_unit == PricingUnit.FIXED:
                base_label = "Базовая стоимость (фиксированная)"
            else:
                base_label = (
                    f"Базовая стоимость ({scenario.volume} x {offer.base_price})"
                )
            price_breakdown.append(PriceLineItem(label=base_label, amount=base_amount))

            for surcharge in offer.surcharges:
                if not surcharge.is_mandatory:
                    continue
                surcharge_amount = _calculate_unit_amount(
                    surcharge.amount,
                    surcharge.unit,
                    scenario,
                )
                if surcharge_amount is None:
                    continue
                if surcharge.unit == PricingUnit.FIXED:
                    surcharge_label = f"Доплата: {surcharge.name}"
                else:
                    surcharge_label = (
                        f"Доплата: {surcharge.name} "
                        f"({scenario.volume} x {surcharge.amount})"
                    )
                price_breakdown.append(
                    PriceLineItem(label=surcharge_label, amount=surcharge_amount)
                )

            total_estimated_price = sum(
                (item.amount for item in price_breakdown),
                Decimal("0"),
            )

    return ComparisonResult(
        offer_id=offer.id,
        provider_name=offer.provider_name,
        status=status,
        completeness=completeness,
        total_estimated_price=total_estimated_price,
        price_breakdown=price_breakdown,
        differences=differences,
        missing_info=missing_info,
    )


_STATUS_ORDER = {
    ComparabilityStatus.COMPARABLE: 0,
    ComparabilityStatus.PARTIALLY_COMPARABLE: 1,
    ComparabilityStatus.NOT_COMPARABLE: 2,
}


def _sort_key(result: ComparisonResult) -> Tuple[int, int, Decimal]:
    status_rank = _STATUS_ORDER[result.status]
    missing_price_rank = 0 if result.total_estimated_price is not None else 1
    price = result.total_estimated_price if result.total_estimated_price is not None else Decimal("0")
    return (status_rank, missing_price_rank, price)


def compare_offers(
    offers: List[ServiceOffer],
    scenario: OrderScenario,
) -> List[ComparisonResult]:
    """Сравнивает список предложений под один сценарий и сортирует результаты."""
    results = [calculate_comparison(offer, scenario) for offer in offers]
    return sorted(results, key=_sort_key)
