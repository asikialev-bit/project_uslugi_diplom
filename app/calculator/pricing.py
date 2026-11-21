from decimal import Decimal
from typing import List, Optional, Tuple

from app.models import (
    FIXED_UNIT,
    ComparabilityStatus,
    ComparisonResult,
    DataCompleteness,
    OrderScenario,
    PriceLineItem,
    ServiceOffer,
    get_unit_conversion_factor,
)
from app.rules import evaluate_offer, surcharge_matches_conditions


def _calculate_unit_amount(
    unit_price: Decimal,
    unit: str,
    scenario: OrderScenario,
) -> Optional[Decimal]:
    """Вычисляет сумму для ставки с учётом единицы расчёта сценария и переводов."""
    if unit == FIXED_UNIT:
        return unit_price
    factor = get_unit_conversion_factor(
        scenario.pricing_unit,
        unit,
        scenario.unit_conversions,
    )
    if factor is None:
        return None
    return unit_price * scenario.volume * factor


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

    # Проверяем совместимость единиц обязательных и активированных доплат
    # независимо от итогового статуса.
    active_surcharges = []
    for surcharge in offer.surcharges:
        activated_by_condition = (
            not surcharge.is_mandatory
            and surcharge_matches_conditions(surcharge, scenario.conditions)
        )
        if not surcharge.is_mandatory and not activated_by_condition:
            continue
        active_surcharges.append((surcharge, activated_by_condition))

        if (
            surcharge.unit != FIXED_UNIT
            and get_unit_conversion_factor(
                scenario.pricing_unit,
                surcharge.unit,
                scenario.unit_conversions,
            )
            is None
        ):
            differences.append(
                f"Невозможно рассчитать доплату «{surcharge.name}»: "
                f"единица '{surcharge.unit}' несовместима со сценарием "
                f"'{scenario.pricing_unit}'"
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
            if offer.pricing_unit == FIXED_UNIT:
                base_label = "Базовая стоимость (фиксированная)"
            else:
                factor = get_unit_conversion_factor(
                    scenario.pricing_unit,
                    offer.pricing_unit,
                    scenario.unit_conversions,
                )
                effective_volume = scenario.volume * (factor or Decimal("1"))
                base_label = (
                    f"Базовая стоимость ({effective_volume} {offer.pricing_unit} "
                    f"x {offer.base_price})"
                )
            price_breakdown.append(PriceLineItem(label=base_label, amount=base_amount))

            for surcharge, activated_by_condition in active_surcharges:
                surcharge_amount = _calculate_unit_amount(
                    surcharge.amount,
                    surcharge.unit,
                    scenario,
                )
                if surcharge_amount is None:
                    continue
                prefix = "Доплата по условию" if activated_by_condition else "Доплата"
                if surcharge.unit == FIXED_UNIT:
                    surcharge_label = f"{prefix}: {surcharge.name}"
                else:
                    factor = get_unit_conversion_factor(
                        scenario.pricing_unit,
                        surcharge.unit,
                        scenario.unit_conversions,
                    )
                    effective_volume = scenario.volume * (factor or Decimal("1"))
                    surcharge_label = (
                        f"{prefix}: {surcharge.name} "
                        f"({effective_volume} {surcharge.unit} x {surcharge.amount})"
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
    price = (
        result.total_estimated_price
        if result.total_estimated_price is not None
        else Decimal("0")
    )
    return (status_rank, missing_price_rank, price)


def compare_offers(
    offers: List[ServiceOffer],
    scenario: OrderScenario,
) -> List[ComparisonResult]:
    """Сравнивает список предложений под один сценарий и сортирует результаты."""
    results = [calculate_comparison(offer, scenario) for offer in offers]
    return sorted(results, key=_sort_key)
