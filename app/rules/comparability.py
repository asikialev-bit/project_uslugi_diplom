from decimal import Decimal
from typing import List, Set

from pydantic import BaseModel, Field

from app.models import (
    FIXED_UNIT,
    ComparabilityStatus,
    OrderScenario,
    ServiceOffer,
    Surcharge,
    get_unit_conversion_factor,
)


class ComparabilityAssessment(BaseModel):
    """Результат оценки сопоставимости предложения со сценарием заказа."""

    status: ComparabilityStatus
    differences: List[str] = Field(default_factory=list)


def _normalize_items(items: List[str]) -> Set[str]:
    return {" ".join(item.strip().lower().split()) for item in items if item.strip()}


def surcharge_matches_conditions(
    surcharge: Surcharge,
    scenario_conditions: List[str],
) -> bool:
    """Проверяет, активируется ли условная доплата условиями сценария."""
    if not scenario_conditions:
        return False
    norm_conditions = _normalize_items(scenario_conditions)
    target = (surcharge.condition_description or surcharge.name).strip().lower()
    if not target:
        return False
    return any(cond in target or target in cond for cond in norm_conditions)


def check_comparability(
    offer: ServiceOffer,
    scenario: OrderScenario,
) -> ComparabilityAssessment:
    """Оценивает уровень сопоставимости предложения со сценарием заказа."""
    differences: List[str] = []
    has_hard_mismatch = False

    conversion_factor: Decimal = Decimal("1")
    if offer.pricing_unit is not None and offer.pricing_unit != scenario.pricing_unit:
        if offer.pricing_unit == FIXED_UNIT:
            differences.append(
                f"Разные единицы расчёта: у предложения '{offer.pricing_unit}', "
                f"в сценарии '{scenario.pricing_unit}' (возможно сравнение по общей сумме)"
            )
        else:
            factor = get_unit_conversion_factor(
                scenario.pricing_unit,
                offer.pricing_unit,
                scenario.unit_conversions,
            )
            if factor is not None:
                conversion_factor = factor
                differences.append(
                    f"Применён пересчёт единиц: '{scenario.pricing_unit}' -> "
                    f"'{offer.pricing_unit}' (коэффициент {factor})"
                )
            else:
                has_hard_mismatch = True
                differences.append(
                    f"Несовместимые единицы расчёта: у предложения '{offer.pricing_unit}', "
                    f"в сценарии '{scenario.pricing_unit}'"
                )

    effective_volume = scenario.volume * conversion_factor
    if offer.min_volume is not None and effective_volume < offer.min_volume:
        has_hard_mismatch = True
        differences.append(
            f"Требуемый объём ({effective_volume}) меньше минимального ({offer.min_volume})"
        )

    if offer.max_volume is not None and effective_volume > offer.max_volume:
        has_hard_mismatch = True
        differences.append(
            f"Требуемый объём ({effective_volume}) больше максимального ({offer.max_volume})"
        )

    exclusions = _normalize_items(offer.exclusions_or_limits)
    required_works = _normalize_items(scenario.required_works)
    required_components = _normalize_items(scenario.required_components)
    scenario_conditions = _normalize_items(scenario.conditions)

    excluded_works = sorted(required_works & exclusions)
    if excluded_works:
        has_hard_mismatch = True
        differences.append(
            "Обязательные работы указаны в ограничениях предложения: "
            + ", ".join(excluded_works)
        )

    excluded_components = sorted(required_components & exclusions)
    if excluded_components:
        has_hard_mismatch = True
        differences.append(
            "Обязательные компоненты указаны в ограничениях предложения: "
            + ", ".join(excluded_components)
        )

    excluded_conditions = sorted(scenario_conditions & exclusions)
    if excluded_conditions:
        has_hard_mismatch = True
        differences.append(
            "Условия сценария указаны в ограничениях предложения: "
            + ", ".join(excluded_conditions)
        )

    if offer.included_works and required_works:
        included_works = _normalize_items(offer.included_works)
        missing_works = sorted(required_works - included_works - exclusions)
        if missing_works:
            differences.append(
                "В базовый состав работ не входят: " + ", ".join(missing_works)
            )

    if offer.included_components and required_components:
        included_components = _normalize_items(offer.included_components)
        missing_components = sorted(
            required_components - included_components - exclusions
        )
        if missing_components:
            differences.append(
                "В базовую стоимость не включены компоненты: "
                + ", ".join(missing_components)
            )

    offer_conditions = _normalize_items(offer.conditions)
    for cond in sorted(scenario_conditions - exclusions):
        covered_by_offer = cond in offer_conditions
        covered_by_surcharge = any(
            surcharge_matches_conditions(s, [cond]) for s in offer.surcharges
        )
        if not covered_by_offer and not covered_by_surcharge:
            differences.append(
                f"Условие сценария «{cond}» не учтено в условиях и доплатах предложения"
            )

    unmatched_conditional_surcharges = [
        s.name
        for s in offer.surcharges
        if not s.is_mandatory
        and not surcharge_matches_conditions(s, scenario.conditions)
    ]
    if unmatched_conditional_surcharges:
        differences.append(
            "Есть условные доплаты, требующие уточнения: "
            + ", ".join(unmatched_conditional_surcharges)
        )

    if has_hard_mismatch:
        status = ComparabilityStatus.NOT_COMPARABLE
    elif differences:
        status = ComparabilityStatus.PARTIALLY_COMPARABLE
    else:
        status = ComparabilityStatus.COMPARABLE

    return ComparabilityAssessment(status=status, differences=differences)
