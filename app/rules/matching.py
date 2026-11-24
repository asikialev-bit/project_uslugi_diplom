from decimal import Decimal
from fractions import Fraction
from typing import Iterable, List, Optional, Set

from pydantic import BaseModel

from app.models import (
    FIXED_UNIT,
    OrderScenario,
    ServiceOffer,
    Surcharge,
    get_unit_conversion_factor,
)


class GeoMatchAssessment(BaseModel):
    """Результат проверки соответствия города и формата оказания услуги."""

    score: int
    is_hard_mismatch: bool
    is_missing: bool
    difference: Optional[str] = None
    detail: str


class UnitVolumeAssessment(BaseModel):
    """Результат проверки совместимости единиц расчёта и ограничений объёма."""

    score: int
    units_compatible: bool
    has_hard_mismatch: bool
    conversion_factor_num: int = 1
    conversion_factor_den: int = 1
    differences: List[str] = []
    detail: str

    @property
    def conversion_factor(self) -> Fraction:
        return Fraction(self.conversion_factor_num, self.conversion_factor_den)


def _format_fraction(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    as_decimal = (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
        Decimal("0.0001")
    )
    return str(as_decimal.normalize())


def normalize_text(value: str) -> str:
    """Нормализует текстовый элемент для нечувствительного к регистру сравнения."""
    return " ".join(value.strip().lower().split())


def normalize_items(items: List[str]) -> Set[str]:
    """Возвращает множество непустых нормализованных строк."""
    return {norm for item in items if (norm := normalize_text(item))}


def text_matches_any(needle: str, haystack: Iterable[str]) -> bool:
    """Проверяет совпадение по равенству или вхождению подстроки."""
    norm_needle = normalize_text(needle)
    if not norm_needle:
        return False
    for raw in haystack:
        norm_candidate = normalize_text(raw)
        if not norm_candidate:
            continue
        if norm_needle in norm_candidate or norm_candidate in norm_needle:
            return True
    return False


def surcharge_matches_conditions(
    surcharge: Surcharge,
    scenario_conditions: List[str],
) -> bool:
    """Проверяет, активируется ли условная доплата условиями сценария."""
    if not scenario_conditions:
        return False
    target = surcharge.condition_description or surcharge.name
    return text_matches_any(target, scenario_conditions)


def assess_geo_match(
    offer: ServiceOffer,
    scenario: OrderScenario,
) -> GeoMatchAssessment:
    """Оценивает совместимость города и онлайн/офлайн формата."""
    sc_city = normalize_text(scenario.city or "")
    of_city = normalize_text(offer.city or "")

    if scenario.is_online and offer.is_online:
        return GeoMatchAssessment(
            score=100,
            is_hard_mismatch=False,
            is_missing=False,
            detail="Обе стороны поддерживают онлайн-формат",
        )

    if scenario.is_online and not offer.is_online:
        if sc_city and of_city:
            if sc_city == of_city:
                return GeoMatchAssessment(
                    score=100,
                    is_hard_mismatch=False,
                    is_missing=False,
                    detail=f"Совпадает город ({offer.city})",
                )
            msg = f"Сценарий допускает онлайн, но предложение только офлайн в городе '{offer.city}'"
            return GeoMatchAssessment(
                score=50,
                is_hard_mismatch=False,
                is_missing=False,
                difference=msg,
                detail=msg,
            )
        if of_city:
            msg = f"Сценарий допускает онлайн, предложение только офлайн ({offer.city})"
            return GeoMatchAssessment(
                score=65,
                is_hard_mismatch=False,
                is_missing=False,
                difference=msg,
                detail=msg,
            )
        msg = "Сценарий допускает онлайн, у предложения формат офлайн без указания города"
        return GeoMatchAssessment(
            score=40,
            is_hard_mismatch=False,
            is_missing=bool(sc_city),
            difference=msg,
            detail=msg,
        )

    # Офлайн-сценарий
    if offer.is_online and not (sc_city and of_city == sc_city):
        msg = "Сценарий требует офлайн-услугу, а предложение только онлайн"
        return GeoMatchAssessment(
            score=0,
            is_hard_mismatch=True,
            is_missing=False,
            difference=msg,
            detail=msg,
        )

    if sc_city and of_city:
        if sc_city == of_city:
            return GeoMatchAssessment(
                score=100,
                is_hard_mismatch=False,
                is_missing=False,
                detail=f"Совпадает город: {offer.city}",
            )
        msg = f"Разные города: в сценарии '{scenario.city}', у предложения '{offer.city}'"
        return GeoMatchAssessment(
            score=0,
            is_hard_mismatch=True,
            is_missing=False,
            difference=msg,
            detail=msg,
        )

    if sc_city and not of_city:
        msg = f"Город исполнителя не указан (в сценарии '{scenario.city}')"
        return GeoMatchAssessment(
            score=30,
            is_hard_mismatch=False,
            is_missing=True,
            difference=msg,
            detail=msg,
        )

    if not sc_city and of_city:
        return GeoMatchAssessment(
            score=75,
            is_hard_mismatch=False,
            is_missing=False,
            detail=f"Город в сценарии не ограничен; предложение в городе {offer.city}",
        )

    return GeoMatchAssessment(
        score=100,
        is_hard_mismatch=False,
        is_missing=False,
        detail="Локация не ограничивалась сценарием",
    )


def assess_unit_volume_match(
    offer: ServiceOffer,
    scenario: OrderScenario,
) -> UnitVolumeAssessment:
    """Оценивает совместимость единиц расчёта, коэффициенты пересчёта и границы объёма."""
    differences: List[str] = []
    has_hard_mismatch = False
    units_compatible = True
    conversion_factor = Fraction(1, 1)
    relation = "exact"

    if offer.pricing_unit is None:
        relation = "missing"
    elif offer.pricing_unit != scenario.pricing_unit:
        if offer.pricing_unit == FIXED_UNIT:
            relation = "fixed_vs_volume"
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
                relation = "converted"
                conversion_factor = factor
                differences.append(
                    f"Применён пересчёт единиц: '{scenario.pricing_unit}' -> "
                    f"'{offer.pricing_unit}' (коэффициент {_format_fraction(factor)})"
                )
            else:
                relation = "incompatible"
                units_compatible = False
                has_hard_mismatch = True
                differences.append(
                    f"Несовместимые единицы расчёта: у предложения '{offer.pricing_unit}', "
                    f"в сценарии '{scenario.pricing_unit}'"
                )

    out_of_bounds = False
    if units_compatible:
        effective_fraction = Fraction(str(scenario.volume)) * conversion_factor
        effective_volume = Decimal(effective_fraction.numerator) / Decimal(
            effective_fraction.denominator
        )
        if offer.min_volume is not None and effective_volume < offer.min_volume:
            has_hard_mismatch = True
            out_of_bounds = True
            differences.append(
                f"Требуемый объём ({_format_fraction(effective_fraction)}) "
                f"меньше минимального ({offer.min_volume})"
            )

        if offer.max_volume is not None and effective_volume > offer.max_volume:
            has_hard_mismatch = True
            out_of_bounds = True
            differences.append(
                f"Требуемый объём ({_format_fraction(effective_fraction)}) "
                f"больше максимального ({offer.max_volume})"
            )

    if relation == "missing":
        score = 0
        detail = "Единица расчёта базовой цены не указана"
    elif relation == "incompatible":
        score = 0
        detail = f"Единицы '{offer.pricing_unit}' и '{scenario.pricing_unit}' несовместимы"
    elif out_of_bounds:
        score = 25 if relation == "exact" else 20
        detail = "Единицы совместимы, но объём заказа выходит за допустимые границы"
    elif relation == "exact":
        score = 100
        detail = f"Прямое совпадение единицы ('{scenario.pricing_unit}') и допустимого объёма"
    elif relation == "converted":
        score = 85
        detail = (
            f"Единицы конвертируются без потерь ('{scenario.pricing_unit}' -> '{offer.pricing_unit}')"
        )
    else:
        score = 60
        detail = "Фиксированная цена за заказ при объёмном сценарии"

    return UnitVolumeAssessment(
        score=score,
        units_compatible=units_compatible,
        has_hard_mismatch=has_hard_mismatch,
        conversion_factor_num=conversion_factor.numerator,
        conversion_factor_den=conversion_factor.denominator,
        differences=differences,
        detail=detail,
    )
