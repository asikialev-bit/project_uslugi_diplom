from typing import List

from pydantic import BaseModel, Field

from app.models import DataCompleteness, OrderScenario, ServiceOffer


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

    for surcharge in offer.surcharges:
        if not surcharge.is_mandatory and not surcharge.condition_description:
            missing_info.append(
                f"Не указано условие применения доплаты «{surcharge.name}»"
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
