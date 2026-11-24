from typing import List

from pydantic import BaseModel, Field

from app.models import DataCompleteness, OrderScenario, ServiceOffer
from app.rules.matching import (
    assess_geo_match,
    normalize_text,
    surcharge_matches_conditions,
    text_matches_any,
)


class CompletenessAssessment(BaseModel):
    """Результат проверки полноты данных предложения для сценария."""

    completeness: DataCompleteness
    missing_info: List[str] = Field(default_factory=list)


def check_completeness(
    offer: ServiceOffer,
    scenario: OrderScenario,
) -> CompletenessAssessment:
    """Проверяет, достаточно ли данных в предложении для расчёта и сравнения."""
    missing_info: List[str] = []
    has_critical_missing = False

    if offer.base_price is None:
        missing_info.append("Не указана базовая цена услуги")
        has_critical_missing = True

    if offer.pricing_unit is None:
        missing_info.append("Не указана единица расчёта базовой цены")
        has_critical_missing = True

    if scenario.required_works and not offer.included_works:
        missing_info.append("Не указан состав работ, входящих в базовую стоимость")

    if scenario.required_components and not offer.included_components:
        missing_info.append("Не указаны включённые компоненты или материалы")

    if assess_geo_match(offer, scenario).is_missing:
        missing_info.append("Не указан город или формат оказания услуги")

    for surcharge in offer.surcharges:
        if not surcharge.is_mandatory and not surcharge.condition_description:
            missing_info.append(
                f"Не указано условие применения доплаты «{surcharge.name}»"
            )

    for cond in scenario.conditions:
        norm_cond = normalize_text(cond)
        if not norm_cond:
            continue
        in_offer = text_matches_any(
            norm_cond, offer.conditions
        ) or text_matches_any(norm_cond, offer.exclusions_or_limits)
        in_surcharges = any(
            surcharge_matches_conditions(s, [norm_cond]) for s in offer.surcharges
        )
        if not in_offer and not in_surcharges:
            missing_info.append(
                f"Не подтверждено влияние условия сценария «{cond}» на цену или выполнение"
            )

    if has_critical_missing:
        status = DataCompleteness.INSUFFICIENT
    elif missing_info:
        status = DataCompleteness.PARTIAL
    else:
        status = DataCompleteness.COMPLETE

    return CompletenessAssessment(
        completeness=status,
        missing_info=missing_info,
    )
