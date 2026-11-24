from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple
from uuid import uuid4

from pydantic import BaseModel, Field

from app.discovery.fetcher import FetchError, PublicPageFetcher
from app.discovery.providers import (
    DiscoveryCandidate,
    SearchProvider,
    SearchProviderError,
    TavilySearchProvider,
    YandexSearchProvider,
    build_search_query,
)
from app.llm import (
    LLMProviderError,
    OfferExtractionError,
    OfferExtractor,
    RuleBasedOfferExtractor,
)
from app.models import OrderScenario, ProviderType, ServiceOffer
from app.storage import SQLiteRepository


class DiscoveryCollectResult(BaseModel):
    """Итоги сбора и извлечения предложений конкурентов для платного отчёта."""

    candidates_found: int = 0
    extracted_offers: List[ServiceOffer] = Field(default_factory=list)
    reused_cached_count: int = 0
    skipped_count: int = 0
    warnings: List[str] = Field(default_factory=list)


class DiscoveryService:
    """Координирует лёгкий поиск кандидатов (до оплаты) и разбор прайсов (после оплаты)."""

    def __init__(
        self,
        search_provider: Optional[SearchProvider] = None,
        fetcher: Optional[PublicPageFetcher] = None,
        extractor: Optional[OfferExtractor] = None,
        rule_extractor: Optional[RuleBasedOfferExtractor] = None,
    ) -> None:
        self.search_provider = search_provider
        self.fetcher = fetcher or PublicPageFetcher()
        self.extractor = extractor
        self.rule_extractor = rule_extractor or RuleBasedOfferExtractor()

    @property
    def is_live_configured(self) -> bool:
        return self.search_provider is not None

    @classmethod
    def from_env(
        cls, extractor: Optional[OfferExtractor] = None
    ) -> "DiscoveryService":
        provider: Optional[SearchProvider] = (
            YandexSearchProvider.from_env() or TavilySearchProvider.from_env()
        )
        return cls(
            search_provider=provider,
            fetcher=PublicPageFetcher(),
            extractor=extractor,
        )

    def discover_candidates(
        self,
        scenario: OrderScenario,
        limit: int = 8,
        repo: Optional[SQLiteRepository] = None,
    ) -> List[DiscoveryCandidate]:
        """Возвращает лёгкий список кандидатов (с кэшем в SQLite, без вызова LLM)."""
        if self.search_provider is None:
            return []
        query = build_search_query(scenario)
        if repo is not None:
            cached = repo.get_cached_search(query)
            if cached is not None:
                return [DiscoveryCandidate.model_validate(item) for item in cached[:limit]]

        candidates = self.search_provider.search(query, limit=limit)
        if repo is not None and candidates:
            repo.save_cached_search(
                query, [c.model_dump() for c in candidates], ttl_hours=24
            )
        return candidates

    def _process_candidate(
        self,
        candidate: DiscoveryCandidate,
        scenario: OrderScenario,
    ) -> Tuple[Optional[ServiceOffer], List[str], bool]:
        """Загружает страницу одного кандидата и извлекает предложение."""
        warnings: List[str] = []
        page_text = ""
        if candidate.url:
            try:
                page_text = self.fetcher.fetch_text(candidate.url)
            except FetchError as exc:
                warnings.append(
                    f"Страница «{candidate.title}» недоступна ({exc}); использован сниппет поиска"
                )

        header = f"{candidate.title}\n{candidate.snippet}".strip()
        raw_text = f"{header}\n\n{page_text}".strip() if page_text else header
        if len(raw_text) < 20:
            return None, warnings, True

        offer: Optional[ServiceOffer] = None
        offer_id = f"disc-{uuid4().hex[:8]}"
        if self.extractor is not None:
            try:
                offer = self.extractor.extract(
                    raw_text=raw_text,
                    offer_id=offer_id,
                    provider_name=candidate.title[:80],
                    target_service=scenario.title,
                )
            except (OfferExtractionError, LLMProviderError) as exc:
                warnings.append(
                    f"LLM-разбор для «{candidate.title}» недоступен ({exc}); применён локальный парсер"
                )

        if offer is None:
            try:
                offer = self.rule_extractor.extract(
                    raw_text=raw_text,
                    offer_id=offer_id,
                    provider_name=candidate.title[:80],
                    service_title=scenario.title,
                    hint_works=scenario.required_works,
                    provider_type=candidate.provider_type,
                )
            except OfferExtractionError as exc:
                warnings.append(f"Не удалось разобрать «{candidate.title}»: {exc}")
                return None, warnings, True

        enriched = offer.model_copy(
            update={
                "source_url": candidate.url,
                "city": scenario.city,
                "is_online": scenario.is_online,
                "provider_type": (
                    offer.provider_type
                    if offer.provider_type != ProviderType.UNKNOWN
                    else candidate.provider_type
                ),
            }
        )
        return enriched, warnings, False

    def _process_batch(
        self,
        candidates: List[DiscoveryCandidate],
        scenario: OrderScenario,
        repo: SQLiteRepository,
        existing_by_url: dict,
        result: DiscoveryCollectResult,
    ) -> None:
        to_process: List[DiscoveryCandidate] = []
        for candidate in candidates:
            if candidate.url and candidate.url in existing_by_url:
                cached_offer = existing_by_url[candidate.url]
                repo.link_offer_to_scenario(scenario.id, cached_offer.id)
                result.extracted_offers.append(cached_offer)
                result.reused_cached_count += 1
            else:
                to_process.append(candidate)

        if not to_process:
            return

        workers = min(5, len(to_process))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            processed = list(
                pool.map(lambda c: self._process_candidate(c, scenario), to_process)
            )

        for enriched, warnings, skipped in processed:
            result.warnings.extend(warnings)
            if skipped or enriched is None:
                result.skipped_count += 1
                continue
            repo.save_offer(enriched)
            repo.link_offer_to_scenario(scenario.id, enriched.id)
            if enriched.source_url:
                existing_by_url[enriched.source_url] = enriched
            result.extracted_offers.append(enriched)

    def collect_offers_for_scenario(
        self,
        scenario: OrderScenario,
        repo: SQLiteRepository,
        limit: int = 15,
        target_priced_offers: int = 3,
    ) -> DiscoveryCollectResult:
        """Собирает и разбирает прайсы конкурентов параллельно (только после оплаты)."""
        result = DiscoveryCollectResult()
        candidates = self.discover_candidates(scenario, limit=limit, repo=repo)
        result.candidates_found = len(candidates)
        if not candidates:
            return result

        existing_by_url = repo.list_fresh_offers_by_url(max_age_days=14)

        # Волна 1: первые 6 кандидатов
        self._process_batch(candidates[:6], scenario, repo, existing_by_url, result)
        priced_count = sum(1 for o in result.extracted_offers if o.base_price is not None)

        # Волна 2: если открытых цен мало, добираем из оставшихся кандидатов
        if priced_count < target_priced_offers and len(candidates) > 6:
            self._process_batch(candidates[6:], scenario, repo, existing_by_url, result)
            priced_count = sum(1 for o in result.extracted_offers if o.base_price is not None)

        # Волна 3: уточнённый поисковый запрос за ценами, если всё ещё < 2 цен
        if priced_count < 2 and self.search_provider is not None:
            seen_urls = {c.url for c in candidates if c.url}
            refined_query = f"{scenario.title.strip()} {scenario.city or ''} стоимость работ рублей".strip()
            try:
                extra = self.search_provider.search(refined_query, limit=6)
                fresh_extra = [c for c in extra if not c.url or c.url not in seen_urls]
                if fresh_extra:
                    result.candidates_found += len(fresh_extra)
                    self._process_batch(fresh_extra, scenario, repo, existing_by_url, result)
            except SearchProviderError:
                pass

        return result
