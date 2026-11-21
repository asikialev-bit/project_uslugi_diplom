from typing import List, Set

from pydantic import BaseModel, Field

from app.models import ComparabilityStatus, OrderScenario, PricingUnit, ServiceOffer


class ComparabilityAssessment(BaseModel):
    """Результат оценки сопоставимости предложения со сценарием заказа."""

    status: ComparabilityStatus
    differences: List[str] = Field(default_factory=list)


def _normalize_items(items: List[str]) -> Set[str]:
    return {item.strip().lower() for item in items if item.strip()}


def check_comparability(
    offer: ServiceOffer,
    scenario: OrderScenario,
) -> ComparabilityAssessment:
    """Оценивает уровень сопоставимости предложения со сценарием заказа."""
    differences: List[str] = []
    has_hard_mismatch = False

    if offer.min_volume is not None and scenario.volume < offer.min_volume:
        has_hard_mismatch = True
        differences.append(
            f"Требуемый объём ({scenario.volume}) меньше минимального ({offer.min_volume})"
        )

    if offer.max_volume is not None and scenario.volume > offer.max_volume:
        has_hard_mismatch = True
        differences.append(
            f"Требуемый объём ({scenario.volume}) больше максимального ({offer.max_volume})"
        )

    if offer.pricing_unit is not None and offer.pricing_unit != scenario.pricing_unit:
        if offer.pricing_unit == PricingUnit.FIXED:
            differences.append(
                f"Разные единицы расчёта: у предложения '{offer.pricing_unit.value}', "
                f"в сценарии '{scenario.pricing_unit.value}' (возможно сравнение по общей сумме)"
            )
        else:
            has_hard_mismatch = True
            differences.append(
                f"Несовместимые единицы расчёта: у предложения '{offer.pricing_unit.value}', "
                f"в сценарии '{scenario.pricing_unit.value}'"
            )

    exclusions = _normalize_items(offer.exclusions_or_limits)
    required_works = _normalize_items(scenario.required_works)
    required_components = _normalize_items(scenario.required_components)

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

    conditional_surcharges = [
        s.name for s in offer.surcharges if not s.is_mandatory
    ]
    if conditional_surcharges:
        differences.append(
            "Есть условные доплаты, требующие уточнения: "
            + ", ".join(conditional_surcharges)
        )

    if has_hard_mismatch:
        status = ComparabilityStatus.NOT_COMPARABLE
    elif differences:
        status = ComparabilityStatus.PARTIALLY_COMPARABLE
    else:
        status = ComparabilityStatus.COMPARABLE

    return ComparabilityAssessment(status=status, differences=differences)
