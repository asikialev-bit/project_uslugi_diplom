from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
import re
from typing import List, Optional, Set, Tuple

from pydantic import BaseModel

from app.models import (
    OrderScenario,
    ServiceOffer,
    SimilarityBreakdown,
    SimilarityFactor,
)
from app.rules.matching import (
    assess_geo_match,
    assess_unit_volume_match,
    normalize_items,
    normalize_text,
    surcharge_matches_conditions,
    text_matches_any,
)

WEIGHT_SCOPE_COVERAGE = 45
WEIGHT_PRICE_TRANSPARENCY = 30
WEIGHT_GEO_AND_FORMAT = 15
WEIGHT_UNIT_AND_VOLUME = 10


class SimilarityAssessment(BaseModel):
    """Результат расчёта взвешенного индекса сходства и его детализации."""

    score: int
    breakdown: SimilarityBreakdown


@dataclass
class _ItemCoverageStats:
    recall: float
    precision: float
    has_offer_items: bool
    included_count: int
    surcharge_count: int
    unknown_count: int
    excluded_count: int
    total_required: int
    detail: str


def _make_factor(score: int, weight: int, details: List[str]) -> SimilarityFactor:
    clamped = max(0, min(100, score))
    contribution = (Decimal(clamped) * Decimal(weight) / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    normalized = contribution.normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal("1"))
    return SimilarityFactor(
        score=clamped,
        weight=weight,
        weighted_contribution=normalized,
        details=details,
    )


def _tokenize_words(text: str) -> Set[str]:
    return {token for token in re.findall(r"[a-zа-яё0-9]+", text.lower()) if len(token) >= 2}


def _compute_title_similarity(scenario_title: str, offer_title: str) -> float:
    norm_s = normalize_text(scenario_title)
    norm_o = normalize_text(offer_title)
    if not norm_s or not norm_o:
        return 0.0
    if norm_s == norm_o:
        return 1.0
    tokens_s = _tokenize_words(norm_s)
    tokens_o = _tokenize_words(norm_o)
    jaccard = len(tokens_s & tokens_o) / len(tokens_s | tokens_o) if (tokens_s | tokens_o) else 0.0
    if norm_s in norm_o or norm_o in norm_s:
        return max(jaccard, 0.9)
    return jaccard


def _evaluate_item_coverage(
    required_items: List[str],
    included_items: List[str],
    exclusions: List[str],
    surcharge_texts: List[str],
    label: str,
) -> Optional[_ItemCoverageStats]:
    """Оценивает покрытие требуемых элементов по 4 состояниям и точность масштаба."""
    req_norm = sorted(normalize_items(required_items))
    if not req_norm:
        return None

    included_count = 0
    surcharge_count = 0
    unknown_count = 0
    excluded_count = 0
    total_points = 0.0

    for item in req_norm:
        if text_matches_any(item, included_items):
            included_count += 1
            total_points += 1.0
        elif text_matches_any(item, exclusions):
            excluded_count += 1
        elif text_matches_any(item, surcharge_texts):
            surcharge_count += 1
            total_points += 0.5
        else:
            unknown_count += 1
            total_points += 0.2

    inc_norm = sorted(normalize_items(included_items))
    if inc_norm:
        matched_in_offer = sum(1 for item in inc_norm if text_matches_any(item, req_norm))
        precision = matched_in_offer / len(inc_norm)
    else:
        precision = 0.0

    recall = total_points / len(req_norm)
    detail = (
        f"{label}: в базе {included_count} из {len(req_norm)}, "
        f"за доплату {surcharge_count}, не указано {unknown_count}, исключено {excluded_count}"
    )
    return _ItemCoverageStats(
        recall=recall,
        precision=precision,
        has_offer_items=bool(inc_norm),
        included_count=included_count,
        surcharge_count=surcharge_count,
        unknown_count=unknown_count,
        excluded_count=excluded_count,
        total_required=len(req_norm),
        detail=detail,
    )


def _score_scope_coverage(
    offer: ServiceOffer,
    scenario: OrderScenario,
) -> SimilarityFactor:
    surcharge_texts = [
        f"{s.name} {s.condition_description or ''}".strip() for s in offer.surcharges
    ]
    works_cov = _evaluate_item_coverage(
        scenario.required_works,
        offer.included_works,
        offer.exclusions_or_limits,
        surcharge_texts,
        "Работы",
    )
    comp_cov = _evaluate_item_coverage(
        scenario.required_components,
        offer.included_components,
        offer.exclusions_or_limits,
        surcharge_texts,
        "Компоненты",
    )
    title_sim = _compute_title_similarity(scenario.title, offer.service_title)
    details: List[str] = []

    if works_cov is None and comp_cov is None:
        details.append("В сценарии не задан детальный состав работ и компонентов; оценка по названию")
        has_scope_list = 1.0 if offer.included_works else 0.5
        raw_score = 0.65 * title_sim + 0.35 * has_scope_list
        return _make_factor(int(round(raw_score * 100)), WEIGHT_SCOPE_COVERAGE, details)

    weighted_recalls: List[Tuple[float, float]] = []
    precisions: List[float] = []
    if works_cov is not None:
        details.append(works_cov.detail)
        weighted_recalls.append((works_cov.recall, 0.70 if comp_cov is not None else 1.0))
        if works_cov.has_offer_items:
            precisions.append(works_cov.precision)
    if comp_cov is not None:
        details.append(comp_cov.detail)
        weighted_recalls.append((comp_cov.recall, 0.30 if works_cov is not None else 1.0))
        if comp_cov.has_offer_items:
            precisions.append(comp_cov.precision)

    recall_score = sum(val * w for val, w in weighted_recalls)
    precision_score = sum(precisions) / len(precisions) if precisions else 0.0
    details.append(f"Совпадение названия услуги: {int(round(title_sim * 100))}%")

    combined = 0.70 * recall_score + 0.15 * precision_score + 0.15 * title_sim
    return _make_factor(int(round(combined * 100)), WEIGHT_SCOPE_COVERAGE, details)


def _score_price_transparency(
    offer: ServiceOffer,
    scenario: OrderScenario,
) -> SimilarityFactor:
    details: List[str] = []

    # 1. Определённость базовой цены (до 35)
    base_points = (20 if offer.base_price is not None else 0) + (
        15 if offer.pricing_unit is not None else 0
    )
    details.append(f"Базовая цена и единица: {base_points}/35")

    # 2. Прозрачность доплат (до 25)
    if not offer.surcharges:
        surcharge_points = 25
        details.append("Доплаты: скрытых или неясных доплат не заявлено (25/25)")
    else:
        clear = sum(
            1
            for s in offer.surcharges
            if s.is_mandatory or bool(s.condition_description)
        )
        surcharge_points = int(round(25 * clear / len(offer.surcharges)))
        details.append(
            f"Доплаты: понятны условия у {clear} из {len(offer.surcharges)} ({surcharge_points}/25)"
        )

    # 3. Явные границы услуги (до 25)
    works_pts = 15 if offer.included_works else (5 if offer.included_components else 0)
    exclusions_pts = 10 if offer.exclusions_or_limits else 0
    scope_points = works_pts + exclusions_pts
    details.append(f"Явные границы работ и исключений: {scope_points}/25")

    # 4. Условия заказа и ограничения объёма (до 15)
    bounds_pts = 7 if (offer.min_volume is not None or offer.max_volume is not None) else 0
    norm_conditions = [normalize_text(c) for c in scenario.conditions if normalize_text(c)]
    if norm_conditions:
        confirmed = sum(
            1
            for cond in norm_conditions
            if text_matches_any(cond, offer.conditions)
            or text_matches_any(cond, offer.exclusions_or_limits)
            or any(surcharge_matches_conditions(s, [cond]) for s in offer.surcharges)
        )
        cond_pts = int(round(8 * confirmed / len(norm_conditions)))
    else:
        cond_pts = 8 if offer.conditions else 4
    conditions_points = bounds_pts + cond_pts
    details.append(f"Условия и лимиты объёма: {conditions_points}/15")

    total = base_points + surcharge_points + scope_points + conditions_points
    return _make_factor(total, WEIGHT_PRICE_TRANSPARENCY, details)


def evaluate_similarity(
    offer: ServiceOffer,
    scenario: OrderScenario,
) -> SimilarityAssessment:
    """Вычисляет многометрический индекс сходства (45/30/15/10)."""
    scope_factor = _score_scope_coverage(offer, scenario)
    transparency_factor = _score_price_transparency(offer, scenario)

    geo_eval = assess_geo_match(offer, scenario)
    geo_factor = _make_factor(geo_eval.score, WEIGHT_GEO_AND_FORMAT, [geo_eval.detail])

    unit_eval = assess_unit_volume_match(offer, scenario)
    unit_factor = _make_factor(unit_eval.score, WEIGHT_UNIT_AND_VOLUME, [unit_eval.detail])

    breakdown = SimilarityBreakdown(
        scope_coverage=scope_factor,
        price_transparency=transparency_factor,
        geo_and_format=geo_factor,
        unit_and_volume=unit_factor,
    )
    total_weighted = (
        scope_factor.weighted_contribution
        + transparency_factor.weighted_contribution
        + geo_factor.weighted_contribution
        + unit_factor.weighted_contribution
    )
    total_score = max(
        0, min(100, int(total_weighted.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    )
    return SimilarityAssessment(score=total_score, breakdown=breakdown)
