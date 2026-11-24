import json
from pathlib import Path
from typing import Optional, Set

from fastapi.testclient import TestClient

from app.discovery import (
    DiscoveryCandidate,
    DiscoveryService,
    FetchError,
    YandexSearchProvider,
    build_search_query,
    extract_visible_text,
    infer_provider_type,
)
from app.discovery.providers import _parse_yandex_search_xml
from app.llm import OfferExtractor, UnitConversionEstimator
from app.main import app, get_discovery_service, get_email_sender
from app.models import OrderScenario, ProviderType, normalize_unit
from app.storage import SQLiteRepository


class _FakeSearchProvider:
    def __init__(self, candidates: list[DiscoveryCandidate]) -> None:
        self.candidates = candidates
        self.queries: list[str] = []

    def search(self, query: str, limit: int = 8) -> list[DiscoveryCandidate]:
        self.queries.append(query)
        return self.candidates[:limit]


class _FakeFetcher:
    def __init__(
        self, pages: dict[str, str], fail_urls: Optional[Set[str]] = None
    ) -> None:
        self.pages = pages
        self.fail_urls = fail_urls or set()
        self.fetched_urls: list[str] = []

    def fetch_text(self, url: str) -> str:
        self.fetched_urls.append(url)
        if url in self.fail_urls:
            raise FetchError("Страница защищена проверкой CAPTCHA и пропущена")
        return self.pages.get(url, "")


class _FakeLLMClient:
    def __init__(self, responses: dict[str, dict]) -> None:
        self.responses = responses
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        for key, payload in self.responses.items():
            if key in user_prompt:
                return json.dumps(payload, ensure_ascii=False)
        raise AssertionError(f"Неожиданный текст для LLM: {user_prompt}")


class _CaptureEmailSender:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {}

    def send_login_code(self, to_email: str, code: str) -> None:
        self.codes[to_email] = code


def test_query_builder_provider_inference_and_html_text() -> None:
    scenario = OrderScenario(
        id="s-1",
        title="Генеральная уборка",
        city="Екатеринбург",
        required_works=["мытьё полов", "санузел"],
    )
    query = build_search_query(scenario)
    assert "Генеральная уборка" in query
    assert "Екатеринбург" in query
    assert "цена прайс" in query

    assert infer_provider_type("Частный мастер Иван — уборка") == ProviderType.PRIVATE
    assert infer_provider_type("ООО Чистый Дом — клининговая компания") == ProviderType.COMPANY
    assert infer_provider_type("Уборка квартир быстро") == ProviderType.UNKNOWN
    from app.discovery.providers import is_relevant_competitor

    assert is_relevant_competitor("Конфигуратор ПК онлайн | DNS", "https://www.dns-shop.ru/configurator/") is False
    assert is_relevant_competitor("Сервисный центр Позитив", "https://pozitive.org/sborka/") is True

    html = "<html><style>.a{color:red}</style><body><h1>Прайс</h1><script>alert(1)</script><p>От 100 руб/кв.м</p></body></html>"
    visible = extract_visible_text(html)
    assert "Прайс" in visible
    assert "От 100 руб/кв.м" in visible
    assert "alert(1)" not in visible
    assert "color:red" not in visible


def test_discovery_collect_uses_cache_and_snippet_fallback(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "disc.db"))
    candidates = [
        DiscoveryCandidate(
            title="Клининговая компания Блеск",
            url="https://example.com/blesk",
            snippet="Генеральная уборка 140 руб за кв.м",
            provider_type=ProviderType.COMPANY,
        ),
        DiscoveryCandidate(
            title="Частный мастер Ольга",
            url="https://example.com/olga",
            snippet="Частный мастер: уборка квартиры 95 руб за кв.м, мытьё полов включено",
            provider_type=ProviderType.PRIVATE,
        ),
    ]
    fetcher = _FakeFetcher(
        pages={"https://example.com/blesk": "Компания Блеск: генеральная уборка 140 руб/кв.м, мытьё полов."},
        fail_urls={"https://example.com/olga"},
    )
    llm = _FakeLLMClient(
        {
            "Блеск": {
                "provider_name": "Блеск",
                "service_title": "Генеральная уборка",
                "base_price": 140,
                "pricing_unit": "sqm",
                "included_works": ["мытьё полов"],
            },
            "Ольга": {
                "provider_name": "Ольга",
                "service_title": "Уборка квартиры",
                "base_price": 95,
                "pricing_unit": "sqm",
                "included_works": ["мытьё полов"],
            },
        }
    )
    service = DiscoveryService(
        search_provider=_FakeSearchProvider(candidates),
        fetcher=fetcher,
        extractor=OfferExtractor(llm),
    )
    scenario = OrderScenario(
        id="s-clean",
        title="Генеральная уборка",
        city="Екатеринбург",
        volume="50",
        pricing_unit="sqm",
        required_works=["мытьё полов"],
    )

    first = service.collect_offers_for_scenario(scenario, repo)
    assert first.candidates_found == 2
    assert len(first.extracted_offers) == 2
    assert llm.calls == 2
    assert len(first.warnings) == 1  # предупреждение о fallback на сниппет для Ольги
    assert len(repo.list_offers()) == 2

    # Повторный вызов берёт из кэша SQLite без повторного вызова LLM и fetcher
    second = service.collect_offers_for_scenario(scenario, repo)
    assert second.reused_cached_count == 2
    assert llm.calls == 2
    assert len(fetcher.fetched_urls) == 2


def test_api_freemium_discovery_does_not_scrape_until_unlock(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api_disc.db'}")
    candidates = [
        DiscoveryCandidate(
            title="Студия Уюта",
            url="https://example.com/uyut",
            snippet="Уборка 130 руб/кв.м",
            provider_type=ProviderType.COMPANY,
        ),
        DiscoveryCandidate(
            title="Частный мастер Сергей",
            url="https://example.com/sergey",
            snippet="Уборка 90 руб/кв.м",
            provider_type=ProviderType.PRIVATE,
        ),
    ]
    fetcher = _FakeFetcher(
        pages={
            "https://example.com/uyut": "Студия Уюта: уборка 130 руб за кв.м, мытьё полов.",
            "https://example.com/sergey": "Частный мастер Сергей: уборка 90 руб за кв.м, мытьё полов.",
        }
    )
    llm = _FakeLLMClient(
        {
            "Уюта": {
                "provider_name": "Студия Уюта",
                "provider_type": "company",
                "service_title": "Уборка",
                "base_price": 130,
                "pricing_unit": "sqm",
                "included_works": ["мытьё полов"],
            },
            "Сергей": {
                "provider_name": "Сергей",
                "provider_type": "private",
                "service_title": "Уборка",
                "base_price": 90,
                "pricing_unit": "sqm",
                "included_works": ["мытьё полов"],
            },
        }
    )
    discovery = DiscoveryService(
        search_provider=_FakeSearchProvider(candidates),
        fetcher=fetcher,
        extractor=OfferExtractor(llm),
    )
    sender = _CaptureEmailSender()
    app.dependency_overrides[get_discovery_service] = lambda: discovery
    app.dependency_overrides[get_email_sender] = lambda: sender

    try:
        client = TestClient(app)
        assert (
            client.post(
                "/scenarios",
                json={
                    "id": "scen-live",
                    "title": "Уборка квартиры",
                    "city": "Екатеринбург",
                    "volume": "50",
                    "pricing_unit": "sqm",
                    "required_works": ["мытьё полов"],
                },
            ).status_code
            == 200
        )

        # До оплаты: лёгкий discovery показывает 1 живой сниппет + 1 скрытый слот, 0 вызовов LLM и fetcher
        free_resp = client.get("/scenarios/scen-live/report")
        assert free_resp.status_code == 200
        free_data = free_resp.json()
        assert free_data["is_unlocked"] is False
        assert free_data["competitors_count"] == 2
        assert free_data["locked_competitors_count"] == 1
        assert free_data["results"][0]["is_locked"] is False
        assert free_data["results"][0]["provider_name"] == "Студия Уюта"
        assert free_data["market_summary"] is None
        assert llm.calls == 0
        assert fetcher.fetched_urls == []

        # Вход + пополнение + оплата 1 кредита -> запускается реальный сбор и разбор
        assert client.post("/auth/request-code", json={"email": "u@example.com"}).status_code == 200
        code = sender.codes["u@example.com"]
        assert (
            client.post("/auth/verify-code", json={"email": "u@example.com", "code": code}).status_code
            == 200
        )
        assert client.post("/credits/topup", json={"amount": 1}).status_code == 200

        unlock_resp = client.post("/scenarios/scen-live/unlock")
        assert unlock_resp.status_code == 200
        paid = unlock_resp.json()
        assert paid["is_unlocked"] is True
        assert paid["competitors_count"] == 2
        assert paid["market_summary"]["min_price"] == "4500"
        assert paid["market_summary"]["max_price"] == "6500"
        assert llm.calls == 2
        assert len(fetcher.fetched_urls) == 2
    finally:
        app.dependency_overrides.clear()


def test_parse_yandex_search_xml_extracts_hlword_text_and_provider_type() -> None:
    xml_sample = """<?xml version="1.0" encoding="utf-8"?>
    <yandexsearch version="1.0">
      <response>
        <results>
          <grouping>
            <group>
              <doc>
                <url>https://clean.example/price</url>
                <title>ООО <hlword>Чистый Дом</hlword> — клининговая компания</title>
                <passages>
                  <passage>Генеральная <hlword>уборка</hlword> от 120 руб/кв.м.</passage>
                </passages>
              </doc>
            </group>
            <group>
              <doc>
                <url>https://master.example/</url>
                <title>Частный мастер Елена — уборка квартир</title>
                <passages>
                  <passage>Мытьё полов и санузла от 90 руб/кв.м</passage>
                </passages>
              </doc>
            </group>
          </grouping>
        </results>
      </response>
    </yandexsearch>"""
    items = _parse_yandex_search_xml(xml_sample, limit=5)
    assert len(items) == 2
    assert items[0].title == "ООО Чистый Дом — клининговая компания"
    assert items[0].url == "https://clean.example/price"
    assert "от 120 руб/кв.м." in items[0].snippet
    assert items[0].provider_type == ProviderType.COMPANY
    assert items[0].source == "yandex"
    assert items[1].provider_type == ProviderType.PRIVATE

    limited = _parse_yandex_search_xml(xml_sample, limit=1)
    assert len(limited) == 1
    assert YandexSearchProvider.from_env() is None or isinstance(
        YandexSearchProvider.from_env(), YandexSearchProvider
    )


def test_parse_yandex_search_xml_skips_images_and_aggregators() -> None:
    xml_noisy = """<?xml version="1.0" encoding="utf-8"?>
    <yandexsearch version="1.0">
      <response>
        <results>
          <grouping>
            <group>
              <doc>
                <url>https://yandex.ru/images/search?text=cleaning</url>
                <title>Картинки по запросу "клининг Екатеринбург"</title>
                <passages><passage>Фотографии уборки</passage></passages>
              </doc>
            </group>
            <group>
              <doc>
                <url>https://www.avito.ru/ekaterinburg/predlozheniya_uslug</url>
                <title>уборка кухни в Екатеринбурге - цены и отзывы | Услуги на Авито</title>
                <passages><passage>Объявления</passage></passages>
              </doc>
            </group>
            <group>
              <doc>
                <url>https://profi.ru/geo-ekt/uborka/</url>
                <title>Вымыть кухню в Екатеринбурге: 97 клинеров со средним рейтингом</title>
                <passages><passage>От 100 руб.</passage></passages>
              </doc>
            </group>
            <group>
              <doc>
                <url>https://cleanbros.ru/ekb/</url>
                <title>Клининг Брос — уборка кухни в Екатеринбурге</title>
                <passages><passage>Уборка кухни от 2500 руб.</passage></passages>
              </doc>
            </group>
          </grouping>
        </results>
      </response>
    </yandexsearch>"""
    items = _parse_yandex_search_xml(xml_noisy, limit=5)
    assert len(items) == 1
    assert items[0].title == "Клининг Брос — уборка кухни в Екатеринбурге"
    assert items[0].url == "https://cleanbros.ru/ekb/"


def test_discovery_falls_back_to_rule_based_extractor_when_llm_absent(
    tmp_path: Path,
) -> None:
    repo = SQLiteRepository(str(tmp_path / "rule_disc.db"))
    candidates = [
        DiscoveryCandidate(
            title="Клининг Профи",
            url="https://profi.example/clean",
            snippet="Генеральная уборка от 135 ₽/кв.м, мытьё полов и санузел, срочно",
            provider_type=ProviderType.COMPANY,
        )
    ]
    service = DiscoveryService(
        search_provider=_FakeSearchProvider(candidates),
        fetcher=_FakeFetcher(pages={}, fail_urls={"https://profi.example/clean"}),
        extractor=None,
    )
    scenario = OrderScenario(
        id="s-rule",
        title="Генеральная уборка",
        city="Екатеринбург",
        volume="50",
        pricing_unit="sqm",
        required_works=["мытьё полов", "санузел"],
    )

    res = service.collect_offers_for_scenario(scenario, repo)
    assert len(res.extracted_offers) == 1
    offer = res.extracted_offers[0]
    assert offer.base_price == 135
    assert offer.pricing_unit == "sqm"
    assert offer.provider_type == ProviderType.COMPANY
    assert "мытьё полов" in offer.included_works
    assert "срочно" in offer.conditions


def test_unit_conversion_estimator_handles_room_hour_and_fixed() -> None:
    assert normalize_unit("комната") == "room"
    assert normalize_unit("м²") == "sqm"

    scen_sqm = OrderScenario(
        id="s-sqm",
        title="Генеральная уборка",
        volume="50",
        pricing_unit="sqm",
    )
    est = UnitConversionEstimator(client=None)
    conv_sqm = est.estimate_conversions(scen_sqm, ["room", "hour", "fixed", "sqm"])
    assert conv_sqm["room"] > 0
    assert conv_sqm["hour"] > 0
    assert "fixed" not in conv_sqm

    scen_fixed = OrderScenario(
        id="s-fix",
        title="Генеральная уборка",
        volume="1",
        pricing_unit="fixed",
    )
    conv_fixed = est.estimate_conversions(scen_fixed, ["sqm", "room"])
    assert conv_fixed["sqm"] == 50
    assert conv_fixed["room"] == 2


def test_live_discovery_isolates_offers_per_scenario(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'isolated.db'}")
    repo = SQLiteRepository(str(tmp_path / "isolated.db"))
    # Предложение от старого сценария «клининг», не привязанное к новому сценарию «стрижка»
    from app.models import ServiceOffer

    repo.save_offer(
        ServiceOffer(
            id="old-cleaning",
            provider_name="ВИП Клининг",
            service_title="Уборка",
            base_price="150",
            pricing_unit="sqm",
        )
    )

    discovery = DiscoveryService(
        search_provider=_FakeSearchProvider(
            [
                DiscoveryCandidate(
                    title="Барбершоп Стрижка",
                    url="https://barber.example/",
                    snippet="Мужская стрижка 1200 руб.",
                    provider_type=ProviderType.COMPANY,
                )
            ]
        ),
        fetcher=_FakeFetcher(pages={"https://barber.example/": "Барбершоп Стрижка: мужская стрижка 1200 руб."}),
        extractor=None,
    )
    app.dependency_overrides[get_discovery_service] = lambda: discovery
    try:
        client = TestClient(app)
        assert (
            client.post(
                "/scenarios",
                json={"id": "scen-hair", "title": "Стрижка", "city": "Екатеринбург"},
            ).status_code
            == 200
        )
        rep = client.get("/scenarios/scen-hair/report")
        assert rep.status_code == 200
        names = [r["provider_name"] for r in rep.json()["results"]]
        assert "ВИП Клининг" not in names
        assert "Барбершоп Стрижка" in names
    finally:
        app.dependency_overrides.clear()


def test_search_cache_avoids_duplicate_provider_calls_and_respects_ttl(
    tmp_path: Path,
) -> None:
    from app.models import ServiceOffer

    repo = SQLiteRepository(db_path=str(tmp_path / "cache.db"))
    search_provider = _FakeSearchProvider(
        [
            DiscoveryCandidate(
                title="Клининг Про",
                url="https://clean.example/1",
                snippet="Уборка от 2000 руб",
                provider_type=ProviderType.COMPANY,
            )
        ]
    )
    discovery = DiscoveryService(
        search_provider=search_provider,
        fetcher=_FakeFetcher(pages={}),
        extractor=None,
    )
    scenario = OrderScenario(
        id="scen-cache",
        title="Уборка квартиры",
        city="Екатеринбург",
    )

    first = discovery.discover_candidates(scenario, limit=5, repo=repo)
    second = discovery.discover_candidates(scenario, limit=5, repo=repo)

    assert len(first) == 1
    assert len(second) == 1
    assert second[0].url == "https://clean.example/1"
    assert len(search_provider.queries) == 1

    repo.save_cached_search(
        "expired query",
        [
            {
                "title": "Old",
                "url": "https://old.example/",
                "snippet": "",
                "provider_type": "company",
            }
        ],
        ttl_hours=-1,
    )
    assert repo.get_cached_search("expired query") is None

    repo.save_offer(
        ServiceOffer(
            id="offer-fresh-1",
            provider_name="Клининг Про",
            service_title="Уборка квартиры",
            base_price="2000",
            pricing_unit="fixed",
            source_url="https://clean.example/1",
        )
    )
    fresh = repo.list_fresh_offers_by_url(max_age_days=14)
    assert "https://clean.example/1" in fresh
