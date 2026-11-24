from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

from app.models import (
    FIXED_UNIT,
    ComparabilityStatus,
    ComparisonReportResponse,
    ComparisonResult,
    DataCompleteness,
    MarketSummary,
    OrderScenario,
    OwnPositioning,
    PriceLineItem,
    PriceRecommendation,
    ProviderType,
    SegmentSummary,
    ServiceOffer,
    get_unit_conversion_factor,
)
from app.rules import evaluate_offer, surcharge_matches_conditions


def _clean_money(amount: Decimal) -> Decimal:
    """Округляет денежную сумму до копеек без лишних хвостовых нулей."""
    rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded == rounded.to_integral_value():
        return rounded.quantize(Decimal("1"))
    return rounded.normalize()


def _format_effective_volume(volume: Decimal, factor: Fraction) -> str:
    effective = Fraction(str(volume)) * factor
    if effective.denominator == 1:
        return str(effective.numerator)
    as_dec = (Decimal(effective.numerator) / Decimal(effective.denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return str(as_dec.normalize())


def _calculate_unit_amount(
    unit_price: Decimal,
    unit: str,
    scenario: OrderScenario,
) -> Optional[Decimal]:
    """Вычисляет точную сумму для ставки с учётом единицы расчёта и рациональных переводов."""
    if unit == FIXED_UNIT:
        return _clean_money(unit_price)
    factor = get_unit_conversion_factor(
        scenario.pricing_unit,
        unit,
        scenario.unit_conversions,
    )
    if factor is None:
        return None
    exact = Fraction(str(unit_price)) * Fraction(str(scenario.volume)) * factor
    amount = Decimal(exact.numerator) / Decimal(exact.denominator)
    return _clean_money(amount)


def calculate_comparison(
    offer: ServiceOffer,
    scenario: OrderScenario,
    own_offer_id: Optional[str] = None,
) -> ComparisonResult:
    """Оценивает предложение под сценарий и при возможности рассчитывает стоимость."""
    evaluation = evaluate_offer(offer, scenario)
    differences = list(evaluation.comparability.differences)
    missing_info = list(evaluation.completeness.missing_info)

    status = evaluation.comparability.status
    completeness = evaluation.completeness.completeness

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
                ) or Fraction(1, 1)
                vol_str = _format_effective_volume(scenario.volume, factor)
                base_label = (
                    f"Базовая стоимость ({vol_str} {offer.pricing_unit} "
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
                    ) or Fraction(1, 1)
                    vol_str = _format_effective_volume(scenario.volume, factor)
                    surcharge_label = (
                        f"{prefix}: {surcharge.name} "
                        f"({vol_str} {surcharge.unit} x {surcharge.amount})"
                    )
                price_breakdown.append(
                    PriceLineItem(label=surcharge_label, amount=surcharge_amount)
                )

            total_estimated_price = _clean_money(
                sum((item.amount for item in price_breakdown), Decimal("0"))
            )

    adjusted_price: Optional[Decimal] = None
    price_range_min: Optional[Decimal] = None
    price_range_max: Optional[Decimal] = None
    adjustment_note: Optional[str] = None
    if total_estimated_price is not None:
        scope_score = evaluation.similarity.breakdown.scope_coverage.score
        transparency_score = evaluation.similarity.breakdown.price_transparency.score
        has_scope_reqs = bool(scenario.required_works or scenario.required_components)

        scope_uplift = Decimal("0")
        notes: List[str] = []
        if has_scope_reqs and scope_score < 100:
            missing_ratio = Decimal(100 - scope_score) / Decimal(100)
            scope_uplift = (missing_ratio * Decimal("0.5")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            notes.append(
                f"поправка +{int(scope_uplift * 100)}% за неполное покрытие состава ({scope_score}%)"
            )

        adjusted_price = _clean_money(total_estimated_price * (Decimal("1") + scope_uplift))

        uncertainty_pct = Decimal("0.05")
        if transparency_score < 85:
            uncertainty_pct = min(
                Decimal("0.25"),
                (Decimal(100 - transparency_score) * Decimal("0.003")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
            )
            notes.append(
                f"погрешность ±{int(uncertainty_pct * 100)}% из-за неполной прозрачности ({transparency_score}%)"
            )

        base_for_band = adjusted_price or total_estimated_price
        price_range_min = _clean_money(base_for_band * (Decimal("1") - uncertainty_pct))
        price_range_max = _clean_money(base_for_band * (Decimal("1") + uncertainty_pct))
        if notes:
            adjustment_note = "; ".join(notes).capitalize() + "."

    return ComparisonResult(
        offer_id=offer.id,
        provider_name=offer.provider_name,
        is_own_company=bool(own_offer_id and offer.id == own_offer_id),
        provider_type=offer.provider_type,
        status=status,
        completeness=completeness,
        similarity_score=evaluation.similarity.score,
        similarity_breakdown=evaluation.similarity.breakdown,
        total_estimated_price=total_estimated_price,
        adjusted_price=adjusted_price,
        price_range_min=price_range_min,
        price_range_max=price_range_max,
        adjustment_note=adjustment_note,
        price_breakdown=price_breakdown,
        differences=differences,
        missing_info=missing_info,
    )


_STATUS_ORDER = {
    ComparabilityStatus.COMPARABLE: 0,
    ComparabilityStatus.PARTIALLY_COMPARABLE: 1,
    ComparabilityStatus.NOT_COMPARABLE: 2,
}


def _sort_key(result: ComparisonResult) -> Tuple[int, int, Decimal, int]:
    status_rank = _STATUS_ORDER[result.status]
    missing_price_rank = 0 if result.total_estimated_price is not None else 1
    price = (
        result.total_estimated_price
        if result.total_estimated_price is not None
        else Decimal("0")
    )
    return (status_rank, missing_price_rank, price, -result.similarity_score)


def compare_offers(
    offers: List[ServiceOffer],
    scenario: OrderScenario,
    own_offer_id: Optional[str] = None,
) -> List[ComparisonResult]:
    """Сравнивает список предложений под один сценарий и сортирует результаты."""
    results = [
        calculate_comparison(offer, scenario, own_offer_id=own_offer_id)
        for offer in offers
    ]
    return sorted(results, key=_sort_key)


def _filter_promo_outliers(
    priced_comparable: List[ComparisonResult],
) -> Tuple[List[ComparisonResult], List[ComparisonResult]]:
    """Отделяет рекламные аномально низкие выбросы (в 5+ раз ниже медианы остальной выборки)."""
    if len(priced_comparable) < 3:
        return priced_comparable, []
    sorted_by_price = sorted(
        priced_comparable,
        key=lambda r: r.total_estimated_price or Decimal("0"),
    )
    prices = [
        r.total_estimated_price
        for r in sorted_by_price
        if r.total_estimated_price is not None
    ]
    median_all = _compute_median(prices)
    if median_all is None or median_all <= 0:
        return priced_comparable, []

    threshold = median_all / Decimal("5")
    valid: List[ComparisonResult] = []
    outliers: List[ComparisonResult] = []
    for item in priced_comparable:
        p = item.total_estimated_price
        if p is not None and p < threshold:
            outliers.append(
                item.model_copy(
                    update={
                        "total_estimated_price": None,
                        "adjusted_price": None,
                        "price_range_min": None,
                        "price_range_max": None,
                        "missing_info": [
                            *item.missing_info,
                            f"Аномально низкая рекламная ставка ({p} ₽ при медиане {median_all} ₽) исключена из расчёта",
                        ],
                    }
                )
            )
        else:
            valid.append(item)

    if not valid:
        return priced_comparable, []
    return valid, outliers


def _compute_median(sorted_prices: List[Decimal]) -> Optional[Decimal]:
    count = len(sorted_prices)
    if count == 0:
        return None
    mid = count // 2
    if count % 2 == 1:
        return _clean_money(sorted_prices[mid])
    return _clean_money((sorted_prices[mid - 1] + sorted_prices[mid]) / Decimal("2"))


def _mask_comparison_result(
    result: ComparisonResult,
    hidden_index: int,
) -> ComparisonResult:
    """Скрывает детали предложения конкурента на сервере для бесплатного режима."""
    return result.model_copy(
        update={
            "offer_id": f"locked-{hidden_index}",
            "provider_name": f"Скрытый конкурент #{hidden_index}",
            "is_locked": True,
            "provider_type": ProviderType.UNKNOWN,
            "total_estimated_price": None,
            "price_breakdown": [],
            "differences": [],
            "missing_info": [],
            "similarity_breakdown": None,
        }
    )


def _compute_price_stats(
    results: List[ComparisonResult],
) -> Tuple[List[ComparisonResult], Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
    priced_comparable = [
        r
        for r in results
        if r.status != ComparabilityStatus.NOT_COMPARABLE
        and r.total_estimated_price is not None
    ]
    sorted_prices = sorted(
        r.total_estimated_price
        for r in priced_comparable
        if r.total_estimated_price is not None
    )
    if not sorted_prices:
        return priced_comparable, None, None, None
    return (
        priced_comparable,
        _clean_money(sorted_prices[0]),
        _compute_median(sorted_prices),
        _clean_money(sorted_prices[-1]),
    )


def _compute_rank_and_diff(
    own_result: ComparisonResult,
    priced_competitors: List[ComparisonResult],
    median_price: Optional[Decimal],
) -> Tuple[int, int, Optional[Decimal], Optional[Decimal]]:
    own_price = own_result.total_estimated_price or Decimal("0")
    ranked_pool = sorted(
        [own_result, *priced_competitors],
        key=lambda r: (r.total_estimated_price or Decimal("0"), -r.similarity_score),
    )
    price_rank = next(
        idx for idx, item in enumerate(ranked_pool, start=1) if item.offer_id == own_result.offer_id
    )
    diff_amount: Optional[Decimal] = None
    diff_percent: Optional[Decimal] = None
    if median_price is not None:
        diff_amount = _clean_money(own_price - median_price)
        if median_price > 0:
            pct = ((own_price - median_price) / median_price * Decimal("100")).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
            diff_percent = (
                pct.quantize(Decimal("1"))
                if pct == pct.to_integral_value()
                else pct.normalize()
            )
    return price_rank, len(ranked_pool), diff_amount, diff_percent


def _format_segment_label(provider_type: ProviderType) -> str:
    if provider_type == ProviderType.COMPANY:
        return "компаний"
    if provider_type == ProviderType.PRIVATE:
        return "частных исполнителей"
    return "сегмента"


def _build_own_positioning(
    own_result: Optional[ComparisonResult],
    comparable_priced_competitors: List[ComparisonResult],
    median_price: Optional[Decimal],
    segments: Dict[str, SegmentSummary],
) -> Optional[OwnPositioning]:
    if own_result is None:
        return None

    own_price = own_result.total_estimated_price
    if (
        own_result.status == ComparabilityStatus.NOT_COMPARABLE
        or own_price is None
    ):
        return OwnPositioning(
            offer_id=own_result.offer_id,
            own_provider_type=own_result.provider_type,
            own_price=own_price,
            own_similarity_score=own_result.similarity_score,
            summary_text=(
                "Ваше предложение пока нельзя напрямую сопоставить по цене: "
                "не хватает данных или есть несовместимость со сценарием."
            ),
        )

    price_rank, ranked_count, diff_amount, diff_percent = _compute_rank_and_diff(
        own_result, comparable_priced_competitors, median_price
    )

    if diff_percent is None:
        summary = (
            f"Сопоставимых конкурентов с расчётной ценой пока не найдено; "
            f"расчётная цена вашей компании: {own_price}."
        )
    elif diff_percent < 0:
        summary = (
            f"По цене вы на {price_rank}-м месте из {ranked_count} сопоставимых "
            f"предложений (ниже медианы рынка на {abs(diff_percent)}%)."
        )
    elif diff_percent > 0:
        summary = (
            f"По цене вы на {price_rank}-м месте из {ranked_count} сопоставимых "
            f"предложений (выше медианы рынка на {diff_percent}%)."
        )
    else:
        summary = (
            f"По цене вы на {price_rank}-м месте из {ranked_count} сопоставимых "
            f"предложений (точно на уровне медианы рынка)."
        )

    seg_rank: Optional[int] = None
    seg_count = 0
    seg_diff_pct: Optional[Decimal] = None
    seg_text: Optional[str] = None
    if own_result.provider_type in (ProviderType.COMPANY, ProviderType.PRIVATE):
        seg_summary = segments.get(own_result.provider_type.value)
        seg_competitors = [
            r
            for r in comparable_priced_competitors
            if r.provider_type == own_result.provider_type
        ]
        if seg_summary and seg_competitors:
            seg_rank, seg_count, _, seg_diff_pct = _compute_rank_and_diff(
                own_result, seg_competitors, seg_summary.median_price
            )
            seg_label = _format_segment_label(own_result.provider_type)
            if seg_diff_pct is not None and seg_diff_pct < 0:
                seg_text = (
                    f"Среди {seg_label}: {seg_rank}-е место из {seg_count} "
                    f"(ниже медианы сегмента на {abs(seg_diff_pct)}%)."
                )
            elif seg_diff_pct is not None and seg_diff_pct > 0:
                seg_text = (
                    f"Среди {seg_label}: {seg_rank}-е место из {seg_count} "
                    f"(выше медианы сегмента на {seg_diff_pct}%)."
                )
            else:
                seg_text = (
                    f"Среди {seg_label}: {seg_rank}-е место из {seg_count} "
                    f"(на уровне медианы сегмента)."
                )

    return OwnPositioning(
        offer_id=own_result.offer_id,
        own_provider_type=own_result.provider_type,
        own_price=own_price,
        price_rank=price_rank,
        ranked_offers_count=ranked_count,
        diff_from_median_amount=diff_amount,
        diff_from_median_percent=diff_percent,
        segment_price_rank=seg_rank,
        segment_ranked_count=seg_count,
        segment_diff_from_median_percent=seg_diff_pct,
        segment_summary_text=seg_text,
        own_similarity_score=own_result.similarity_score,
        summary_text=summary,
    )


def _build_price_recommendation(
    priced_comparable: List[ComparisonResult],
    own_result: Optional[ComparisonResult],
) -> PriceRecommendation:
    """Формирует ценовую рекомендацию с учётом сходства и приведённых цен."""
    count = len(priced_comparable)
    if count == 0:
        return PriceRecommendation(
            confidence="insufficient",
            based_on_count=0,
            strategy_text=(
                "Недостаточно открытых цен у сопоставимых конкурентов для расчёта "
                "ценового коридора. Уточните детали услуги или проверьте компании без публичной цены ниже."
            ),
        )

    weighted_sum = Decimal("0")
    total_weight = Decimal("0")
    adjusted_values: List[Decimal] = []
    for item in priced_comparable:
        price_val = item.adjusted_price or item.total_estimated_price
        if price_val is None:
            continue
        adjusted_values.append(price_val)
        weight = Decimal(max(10, item.similarity_score))
        weighted_sum += price_val * weight
        total_weight += weight

    sorted_adj = sorted(adjusted_values)
    rec_optimal = _clean_money(weighted_sum / total_weight) if total_weight > 0 else _compute_median(sorted_adj)
    rec_min = _clean_money((rec_optimal or Decimal("0")) * Decimal("0.85"))
    rec_max = _clean_money((rec_optimal or Decimal("0")) * Decimal("1.15"))

    if own_result is not None and own_result.similarity_breakdown is not None:
        own_scope = own_result.similarity_breakdown.scope_coverage.score
        avg_scope = sum(
            r.similarity_breakdown.scope_coverage.score
            for r in priced_comparable
            if r.similarity_breakdown is not None
        ) / max(1, count)
        if own_scope > avg_scope + 10 and rec_optimal is not None:
            rec_optimal = _clean_money(rec_optimal * Decimal("1.08"))
            rec_max = _clean_money(rec_max * Decimal("1.1"))

    confidence = "high" if count >= 3 else ("medium" if count == 2 else "low")
    strategy = (
        f"Рекомендуемый ориентир цены: {rec_optimal} ₽ (коридор {rec_min}–{rec_max} ₽) "
        f"на основе {count} сопоставимых предложений с учётом состава и доплат."
    )
    if own_result is not None and own_result.total_estimated_price is not None and rec_min and rec_max:
        own_p = own_result.total_estimated_price
        if own_p < rec_min:
            strategy += f" Ваша текущая цена ({own_p} ₽) ниже коридора — есть запас повысить чек."
        elif own_p > rec_max:
            strategy += f" Ваша текущая цена ({own_p} ₽) выше коридора — важно обосновать её расширенным составом или сервисом."
        else:
            strategy += f" Ваша текущая цена ({own_p} ₽) находится в конкурентном коридоре."

    return PriceRecommendation(
        confidence=confidence,
        recommended_min=rec_min,
        recommended_optimal=rec_optimal,
        recommended_max=rec_max,
        based_on_count=count,
        strategy_text=strategy,
    )


def build_comparison_report(
    offers: List[ServiceOffer],
    scenario: OrderScenario,
    own_offer_id: Optional[str] = None,
    is_unlocked: bool = False,
) -> ComparisonReportResponse:
    """Формирует структурированный отчёт (freemium-превью или полный платный отчёт)."""
    all_results = compare_offers(offers, scenario, own_offer_id=own_offer_id)
    own_result = next((r for r in all_results if r.is_own_company), None)
    competitors = [r for r in all_results if not r.is_own_company]

    if is_unlocked:
        raw_priced_comparable, _, _, _ = _compute_price_stats(competitors)
        priced_comparable, promo_outliers = _filter_promo_outliers(raw_priced_comparable)
        outlier_ids = {o.offer_id for o in promo_outliers}
        clean_competitors = [
            o for o in competitors if o.offer_id not in outlier_ids
        ] + promo_outliers

        _, min_p, median_p, max_p = _compute_price_stats(priced_comparable)
        segments: Dict[str, SegmentSummary] = {}
        for ptype in (ProviderType.COMPANY, ProviderType.PRIVATE):
            seg_all = [r for r in clean_competitors if r.provider_type == ptype]
            if not seg_all:
                continue
            seg_priced, s_min, s_med, s_max = _compute_price_stats(seg_all)
            segments[ptype.value] = SegmentSummary(
                provider_type=ptype,
                total_offers_found=len(seg_all),
                comparable_offers_count=len(seg_priced),
                min_price=s_min,
                median_price=s_med,
                max_price=s_max,
            )

        market_summary = MarketSummary(
            total_offers_found=len(clean_competitors),
            comparable_offers_count=len(priced_comparable),
            min_price=min_p,
            median_price=median_p,
            max_price=max_p,
            segments=segments,
        )
        own_positioning = _build_own_positioning(
            own_result, priced_comparable, median_p, segments
        )
        price_recommendation = _build_price_recommendation(
            priced_comparable, own_result
        )
        unpriced = (
            [r for r in clean_competitors if r.total_estimated_price is None]
            if priced_comparable
            else []
        )
        main_results = (
            [
                r
                for r in ([own_result] if own_result else []) + clean_competitors
                if r.is_own_company or r.total_estimated_price is not None
            ]
            if unpriced
            else ([own_result] if own_result else []) + clean_competitors
        )
        return ComparisonReportResponse(
            scenario_id=scenario.id,
            is_unlocked=True,
            competitors_count=len(clean_competitors),
            locked_competitors_count=0,
            own_result=own_result,
            market_summary=market_summary,
            own_positioning=own_positioning,
            price_recommendation=price_recommendation,
            results=main_results,
            unpriced_results=unpriced,
        )

    # Freemium-режим: свой аудит открыт, максимум 1 конкурент открыт как пример,
    # остальные конкуренты скрыты на бэкенде; рыночная сводка и позиционирование не отдаются.
    visible_results: List[ComparisonResult] = []
    competitor_idx = 0
    locked_count = 0
    for item in all_results:
        if item.is_own_company:
            visible_results.append(item)
            continue
        if competitor_idx == 0:
            visible_results.append(item)
        else:
            visible_results.append(_mask_comparison_result(item, competitor_idx))
            locked_count += 1
        competitor_idx += 1

    return ComparisonReportResponse(
        scenario_id=scenario.id,
        is_unlocked=False,
        competitors_count=len(competitors),
        locked_competitors_count=locked_count,
        own_result=own_result,
        market_summary=None,
        own_positioning=None,
        results=visible_results,
    )
