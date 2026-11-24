from typing import List

from pydantic import BaseModel, Field

from app.models import ComparabilityStatus, OrderScenario, ServiceOffer
from app.rules.matching import (
    assess_geo_match,
    assess_unit_volume_match,
    normalize_items,
    surcharge_matches_conditions,
    text_matches_any,
)


class ComparabilityAssessment(BaseModel):
    """Результат оценки сопоставимости предложения со сценарием заказа."""

    status: ComparabilityStatus
    differences: List[str] = Field(default_factory=list)


def check_comparability(
    offer: ServiceOffer,
    scenario: OrderScenario,
) -> ComparabilityAssessment:
    """Оценивает уровень сопоставимости предложения со сценарием заказа."""
    unit_eval = assess_unit_volume_match(offer, scenario)
    differences: List[str] = list(unit_eval.differences)
    has_hard_mismatch = unit_eval.has_hard_mismatch

    geo_eval = assess_geo_match(offer, scenario)
    if geo_eval.is_hard_mismatch:
        has_hard_mismatch = True
    if geo_eval.difference:
        differences.append(geo_eval.difference)

    required_works = normalize_items(scenario.required_works)
    required_components = normalize_items(scenario.required_components)
    scenario_conditions = normalize_items(scenario.conditions)

    excluded_works = sorted(
        w for w in required_works if text_matches_any(w, offer.exclusions_or_limits)
    )
    if excluded_works:
        has_hard_mismatch = True
        differences.append(
            "Обязательные работы указаны в ограничениях предложения: "
            + ", ".join(excluded_works)
        )

    excluded_components = sorted(
        c
        for c in required_components
        if text_matches_any(c, offer.exclusions_or_limits)
    )
    if excluded_components:
        has_hard_mismatch = True
        differences.append(
            "Обязательные компоненты указаны в ограничениях предложения: "
            + ", ".join(excluded_components)
        )

    excluded_conditions = sorted(
        c
        for c in scenario_conditions
        if text_matches_any(c, offer.exclusions_or_limits)
    )
    if excluded_conditions:
        has_hard_mismatch = True
        differences.append(
            "Условия сценария указаны в ограничениях предложения: "
            + ", ".join(excluded_conditions)
        )

    if offer.included_works and required_works:
        missing_works = sorted(
            w
            for w in required_works
            if not text_matches_any(w, offer.included_works)
            and not text_matches_any(w, offer.exclusions_or_limits)
        )
        if missing_works:
            differences.append(
                "В базовый состав работ не входят: " + ", ".join(missing_works)
            )

    if offer.included_components and required_components:
        missing_components = sorted(
            c
            for c in required_components
            if not text_matches_any(c, offer.included_components)
            and not text_matches_any(c, offer.exclusions_or_limits)
        )
        if missing_components:
            differences.append(
                "В базовую стоимость не включены компоненты: "
                + ", ".join(missing_components)
            )

    for cond in sorted(scenario_conditions):
        if text_matches_any(cond, offer.exclusions_or_limits):
            continue
        covered_by_offer = text_matches_any(cond, offer.conditions)
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
