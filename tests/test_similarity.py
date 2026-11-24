from decimal import Decimal

from app.calculator import calculate_comparison, compare_offers
from app.models import (
    ComparabilityStatus,
    DataCompleteness,
    OrderScenario,
    ServiceOffer,
    Surcharge,
)
from app.rules import evaluate_similarity


def _cleaning_scenario() -> OrderScenario:
    return OrderScenario(
        id="scen-clean",
        title="Генеральная уборка квартиры",
        required_works=[
            "мытьё полов",
            "чистка санузла",
            "уборка кухни",
            "обеспыливание",
        ],
        volume=Decimal("60"),
        pricing_unit="sqm",
        required_components=["моющие средства"],
        conditions=["срочный выезд"],
        city="Екатеринбург",
        is_online=False,
    )


def _ideal_offer() -> ServiceOffer:
    return ServiceOffer(
        id="offer-ideal",
        provider_name="Чистый Дом",
        service_title="Генеральная уборка квартиры",
        base_price=Decimal("120"),
        pricing_unit="sqm",
        included_works=[
            "мытьё полов",
            "чистка санузла",
            "уборка кухни",
            "обеспыливание",
        ],
        included_components=["моющие средства"],
        exclusions_or_limits=["мойка фасадов"],
        surcharges=[
            Surcharge(
                name="Срочный выезд",
                amount=Decimal("500"),
                unit="fixed",
                is_mandatory=False,
                condition_description="срочный выезд",
            )
        ],
        min_volume=Decimal("20"),
        max_volume=Decimal("200"),
        conditions=["срочный выезд"],
        city="Екатеринбург",
        is_online=False,
        source_url="https://example.com/clean",
    )


def test_ideal_offer_gets_full_100_similarity_and_weights() -> None:
    assessment = evaluate_similarity(_ideal_offer(), _cleaning_scenario())
    bd = assessment.breakdown

    assert bd.scope_coverage.weight == 45
    assert bd.price_transparency.weight == 30
    assert bd.geo_and_format.weight == 15
    assert bd.unit_and_volume.weight == 10
    assert (
        bd.scope_coverage.weight
        + bd.price_transparency.weight
        + bd.geo_and_format.weight
        + bd.unit_and_volume.weight
        == 100
    )

    assert bd.scope_coverage.score == 100
    assert bd.price_transparency.score == 100
    assert bd.geo_and_format.score == 100
    assert bd.unit_and_volume.score == 100
    assert assessment.score == 100


def test_scope_coverage_distinguishes_base_surcharge_unknown_and_excluded() -> None:
    scenario = _cleaning_scenario()
    base_only = _ideal_offer()

    via_surcharge = _ideal_offer().model_copy(
        update={
            "id": "offer-surcharge",
            "included_works": ["мытьё полов", "чистка санузла"],
            "surcharges": [
                Surcharge(
                    name="уборка кухни",
                    amount=Decimal("800"),
                    unit="fixed",
                    is_mandatory=False,
                    condition_description="уборка кухни",
                ),
                Surcharge(
                    name="Срочный выезд",
                    amount=Decimal("500"),
                    unit="fixed",
                    is_mandatory=False,
                    condition_description="срочный выезд",
                ),
            ],
        }
    )

    bloated_turnkey = _ideal_offer().model_copy(
        update={
            "id": "offer-bloated",
            "service_title": "Комплексный ремонт и уборка",
            "included_works": [
                "мытьё полов",
                "чистка санузла",
                "уборка кухни",
                "обеспыливание",
                "штукатурка стен",
                "укладка плитки",
                "монтаж электрики",
                "вывоз строительного мусора",
                "замена розеток",
                "покраска потолка",
            ],
        }
    )

    excluded_work = _ideal_offer().model_copy(
        update={
            "id": "offer-excluded",
            "included_works": ["мытьё полов", "чистка санузла"],
            "exclusions_or_limits": ["уборка кухни", "обеспыливание"],
        }
    )

    s_ideal = evaluate_similarity(base_only, scenario).breakdown.scope_coverage.score
    s_surcharge = evaluate_similarity(via_surcharge, scenario).breakdown.scope_coverage.score
    s_bloated = evaluate_similarity(bloated_turnkey, scenario).breakdown.scope_coverage.score
    s_excluded = evaluate_similarity(excluded_work, scenario).breakdown.scope_coverage.score

    assert s_ideal > s_bloated
    assert s_ideal > s_surcharge > s_excluded


def test_price_transparency_penalizes_missing_fields_and_unclear_surcharges() -> None:
    scenario = _cleaning_scenario()
    opaque_offer = ServiceOffer(
        id="offer-opaque",
        provider_name="Мутно Сервис",
        service_title="Уборка",
        base_price=None,
        pricing_unit=None,
        included_works=[],
        exclusions_or_limits=[],
        surcharges=[
            Surcharge(
                name="Сложность",
                amount=Decimal("1000"),
                unit="fixed",
                is_mandatory=False,
                condition_description=None,
            )
        ],
        city="Екатеринбург",
    )

    assessment = evaluate_similarity(opaque_offer, scenario)
    assert assessment.breakdown.price_transparency.score == 0
    assert assessment.breakdown.unit_and_volume.score == 0


def test_geo_and_format_matching_and_comparability() -> None:
    scenario = _cleaning_scenario()

    other_city = _ideal_offer().model_copy(update={"id": "o-msk", "city": "Москва"})
    res_other_city = calculate_comparison(other_city, scenario)
    assert res_other_city.status == ComparabilityStatus.NOT_COMPARABLE
    assert res_other_city.similarity_breakdown is not None
    assert res_other_city.similarity_breakdown.geo_and_format.score == 0

    case_diff_city = _ideal_offer().model_copy(update={"city": "  екатеринбург  "})
    res_same_city = calculate_comparison(case_diff_city, scenario)
    assert res_same_city.status == ComparabilityStatus.COMPARABLE
    assert res_same_city.similarity_breakdown is not None
    assert res_same_city.similarity_breakdown.geo_and_format.score == 100

    missing_city = _ideal_offer().model_copy(update={"city": None})
    res_missing_city = calculate_comparison(missing_city, scenario)
    assert res_missing_city.completeness == DataCompleteness.PARTIAL
    assert any("город" in item.lower() for item in res_missing_city.missing_info)
    assert res_missing_city.similarity_breakdown is not None
    assert res_missing_city.similarity_breakdown.geo_and_format.score == 30

    online_scenario = OrderScenario(
        id="scen-online",
        title="Консультация юриста",
        volume=Decimal("60"),
        pricing_unit="minute",
        is_online=True,
    )
    online_offer = ServiceOffer(
        id="offer-online",
        provider_name="ЮрОнлайн",
        service_title="Консультация юриста",
        base_price=Decimal("2000"),
        pricing_unit="hour",
        is_online=True,
    )
    res_online = calculate_comparison(online_offer, online_scenario)
    assert res_online.status == ComparabilityStatus.PARTIALLY_COMPARABLE
    assert res_online.similarity_breakdown is not None
    assert res_online.similarity_breakdown.geo_and_format.score == 100
    assert res_online.similarity_breakdown.unit_and_volume.score == 85


def test_compare_offers_uses_similarity_score_when_prices_tie() -> None:
    scenario = _cleaning_scenario()
    ideal = _ideal_offer().model_copy(update={"id": "ideal", "base_price": Decimal("120")})
    less_transparent = _ideal_offer().model_copy(
        update={
            "id": "less-transparent",
            "base_price": Decimal("120"),
            "exclusions_or_limits": [],
            "min_volume": None,
            "max_volume": None,
        }
    )

    results = compare_offers([less_transparent, ideal], scenario)
    assert [r.offer_id for r in results] == ["ideal", "less-transparent"]
    assert results[0].similarity_score > results[1].similarity_score
