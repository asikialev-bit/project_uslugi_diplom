from decimal import Decimal
from fractions import Fraction
from typing import Dict, Optional, Tuple

FIXED_UNIT = "fixed"

_UNIT_ALIASES: Dict[str, str] = {
    "fixed": FIXED_UNIT,
    "fix": FIXED_UNIT,
    "фикс": FIXED_UNIT,
    "фиксированная": FIXED_UNIT,
    "за услугу": FIXED_UNIT,
    "за проект": FIXED_UNIT,
    "per_hour": "hour",
    "hour": "hour",
    "hours": "hour",
    "час": "hour",
    "часы": "hour",
    "ч": "hour",
    "minute": "minute",
    "minutes": "minute",
    "мин": "minute",
    "минута": "minute",
    "per_sqm": "sqm",
    "sqm": "sqm",
    "m2": "sqm",
    "м2": "sqm",
    "кв.м": "sqm",
    "кв. м": "sqm",
    "per_unit": "unit",
    "unit": "unit",
    "units": "unit",
    "шт": "unit",
    "штука": "unit",
    "ед": "unit",
    "единица": "unit",
    "km": "km",
    "км": "km",
    "m": "meter",
    "meter": "meter",
    "м": "meter",
    "метр": "meter",
    "kg": "kg",
    "кг": "kg",
    "g": "gram",
    "gram": "gram",
    "г": "gram",
    "month": "month",
    "мес": "month",
    "месяц": "month",
    "session": "session",
    "сеанс": "session",
    "занятие": "session",
}

# Точные рациональные коэффициенты: (из_единицы, в_единицу) -> Fraction.
_EXACT_CONVERSIONS: Dict[Tuple[str, str], Fraction] = {
    ("hour", "minute"): Fraction(60, 1),
    ("minute", "hour"): Fraction(1, 60),
    ("km", "meter"): Fraction(1000, 1),
    ("meter", "km"): Fraction(1, 1000),
    ("kg", "gram"): Fraction(1000, 1),
    ("gram", "kg"): Fraction(1, 1000),
}


def normalize_unit(raw_unit: str) -> str:
    """Приводит название единицы расчёта к каноническому виду."""
    cleaned = " ".join(raw_unit.strip().lower().split())
    if not cleaned:
        raise ValueError("Единица расчёта не может быть пустой")
    return _UNIT_ALIASES.get(cleaned, cleaned)


def get_unit_conversion_factor(
    scenario_unit: str,
    offer_unit: str,
    custom_conversions: Optional[Dict[str, Decimal]] = None,
) -> Optional[Fraction]:
    """Возвращает точный рациональный множитель для перевода объёма сценария в единицы предложения."""
    norm_scenario = normalize_unit(scenario_unit)
    norm_offer = normalize_unit(offer_unit)

    if norm_scenario == norm_offer:
        return Fraction(1, 1)

    if custom_conversions:
        normalized_custom = {
            normalize_unit(k): v for k, v in custom_conversions.items()
        }
        if norm_offer in normalized_custom:
            return Fraction(str(normalized_custom[norm_offer]))

    return _EXACT_CONVERSIONS.get((norm_scenario, norm_offer))
