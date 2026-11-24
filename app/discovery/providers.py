import base64
import os
from typing import List, Optional, Protocol
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import httpx
from pydantic import BaseModel, Field

from app.models import OrderScenario, ProviderType


class DiscoveryCandidate(BaseModel):
    """Лёгкий кандидат конкурента, найденный до скачивания прайса и LLM."""

    title: str = Field(..., min_length=1)
    url: Optional[str] = None
    snippet: str = ""
    provider_type: ProviderType = ProviderType.UNKNOWN
    source: str = "search"


class SearchProviderError(Exception):
    """Ошибка внешнего поискового API."""


class SearchProvider(Protocol):
    """Интерфейс легального провайдера поиска конкурентов."""

    def search(self, query: str, limit: int = 8) -> List[DiscoveryCandidate]:
        """Возвращает список кандидатов по поисковому запросу."""


def infer_provider_type(title: str, snippet: str = "", url: Optional[str] = None) -> ProviderType:
    """Определяет сегмент (компания / частник) по явным текстовым маркерам."""
    combined = f"{title} {snippet} {url or ''}".lower()
    private_markers = (
        "частный мастер",
        "частный специалист",
        "частник",
        "самозанятый",
        "фрилансер",
        "работаю сам",
        "работаю без посредников",
        "без посредников",
        "на дому у вас",
        "мастер на дом",
        "ип ",
        "частный ",
        "вызов мастера",
    )
    company_markers = (
        "ооо ",
        "«",
        "компания",
        "агентство",
        "студия",
        "сервисный центр",
        "сервис",
        "фирма",
        "центр ",
        "бюро",
        "мастерская",
    )
    if any(m in combined for m in private_markers):
        return ProviderType.PRIVATE
    if any(m in combined for m in company_markers):
        return ProviderType.COMPANY
    return ProviderType.UNKNOWN


_EXCLUDED_DOMAINS = (
    "yandex.ru",
    "ya.ru",
    "avito.ru",
    "profi.ru",
    "youdo.com",
    "youla.ru",
    "2gis.ru",
    "zoon.ru",
    "flamp.ru",
    "irecommend.ru",
    "otzovik.com",
    "youtube.com",
    "vk.com",
    "dzen.ru",
    "dns-shop.ru",
    "citilink.ru",
    "mvideo.ru",
    "eldorado.ru",
    "ozon.ru",
    "wildberries.ru",
    "market.yandex.ru",
    "regard.ru",
)

_NOISE_TITLE_MARKERS = (
    "картинки по запросу",
    "видео по запросу",
    "конфигуратор пк",
    "онлайн-конфигуратор",
    "услуги на авито",
    "цены и отзывы",
    "топ-10",
    "топ 10",
    "рейтинг лучших",
    "исполнителей со средним",
    "клинеров со средним",
    "мастеров со средним",
)


def is_relevant_competitor(title: str, url: Optional[str], snippet: str = "") -> bool:
    """Отсеивает колдунщики поисковика, картинки и общие каталоги-агрегаторы."""
    norm_title = title.strip().lower()
    if any(marker in norm_title for marker in _NOISE_TITLE_MARKERS):
        return False

    if url:
        host = urlparse(url).netloc.lower()
        if any(host == dom or host.endswith(f".{dom}") for dom in _EXCLUDED_DOMAINS):
            return False

    return True


def build_search_query(scenario: OrderScenario) -> str:
    """Формирует поисковый запрос из названия услуги, города и ключевых работ."""
    title = scenario.title.strip()
    parts = [title]
    if "услуг" not in title.lower():
        parts.append("услуга")
    if scenario.city:
        parts.append(scenario.city.strip())
    elif scenario.is_online:
        parts.append("онлайн")
    if scenario.required_works:
        parts.extend(w.strip() for w in scenario.required_works[:3] if w.strip())
    parts.append("цена прайс")
    return " ".join(parts)


class TavilySearchProvider:
    """Официальный поиск через Tavily Search API."""

    def __init__(
        self,
        api_key: str,
        endpoint: str = "https://api.tavily.com/search",
        timeout_seconds: float = 12.0,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> Optional["TavilySearchProvider"]:
        api_key = os.getenv("TAVILY_API_KEY", "").strip()
        if not api_key:
            return None
        endpoint = os.getenv("TAVILY_API_URL", "https://api.tavily.com/search").strip()
        return cls(api_key=api_key, endpoint=endpoint)

    def search(self, query: str, limit: int = 8) -> List[DiscoveryCandidate]:
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max(1, min(limit, 15)),
            "include_raw_content": False,
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(self.endpoint, json=payload)
        except httpx.HTTPError as exc:
            raise SearchProviderError(f"Ошибка сети при поиске (Tavily): {exc}") from exc

        if response.status_code >= 400:
            raise SearchProviderError(
                f"Tavily Search API вернул HTTP {response.status_code}"
            )

        data = response.json()
        raw_results = data.get("results") or []
        candidates: List[DiscoveryCandidate] = []
        for item in raw_results:
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip() or None
            snippet = str(item.get("content") or "").strip()
            if not title:
                continue
            candidates.append(
                DiscoveryCandidate(
                    title=title,
                    url=url,
                    snippet=snippet,
                    provider_type=infer_provider_type(title, snippet, url),
                    source="tavily",
                )
            )
        return candidates


def _parse_yandex_search_xml(xml_text: str, limit: int) -> List[DiscoveryCandidate]:
    """Разбирает XML-выдачу Yandex Search API v2 в список кандидатов."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SearchProviderError(f"Yandex Search API вернул некорректный XML: {exc}") from exc

    error_el = root.find(".//error")
    if error_el is not None:
        if error_el.attrib.get("code") == "15":
            return []
        err_text = "".join(error_el.itertext()).strip()
        raise SearchProviderError(f"Ошибка Yandex Search API: {err_text}")

    candidates: List[DiscoveryCandidate] = []
    for doc in root.findall(".//doc"):
        url_el = doc.find("url")
        title_el = doc.find("title")
        url = "".join(url_el.itertext()).strip() if url_el is not None else ""
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        if not title:
            continue

        passages = [
            " ".join("".join(p.itertext()).split())
            for p in doc.findall(".//passages/passage")
        ]
        snippet = " ".join(p for p in passages if p).strip()
        if not is_relevant_competitor(title, url or None, snippet):
            continue
        candidates.append(
            DiscoveryCandidate(
                title=title,
                url=url or None,
                snippet=snippet,
                provider_type=infer_provider_type(title, snippet, url or None),
                source="yandex",
            )
        )
        if len(candidates) >= limit:
            break
    return candidates


class YandexSearchProvider:
    """Официальный поиск через Yandex Cloud Search API v2 (Текстовый поиск)."""

    def __init__(
        self,
        api_key: str,
        folder_id: str,
        endpoint: str = "https://searchapi.api.cloud.yandex.net/v2/web/search",
        timeout_seconds: float = 12.0,
    ) -> None:
        self.api_key = api_key
        self.folder_id = folder_id
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> Optional["YandexSearchProvider"]:
        api_key = os.getenv("YANDEX_SEARCH_API_KEY", "").strip()
        folder_id = os.getenv("YANDEX_FOLDER_ID", "").strip()
        if not api_key or not folder_id:
            return None
        endpoint = os.getenv(
            "YANDEX_SEARCH_API_URL",
            "https://searchapi.api.cloud.yandex.net/v2/web/search",
        ).strip()
        return cls(api_key=api_key, folder_id=folder_id, endpoint=endpoint)

    def search(self, query: str, limit: int = 8) -> List[DiscoveryCandidate]:
        payload = {
            "query": {
                "searchType": "SEARCH_TYPE_RU",
                "queryText": query,
                "familyMode": "FAMILY_MODE_MODERATE",
                "page": "0",
            },
            "folderId": self.folder_id,
            "responseFormat": "FORMAT_XML",
        }
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(self.endpoint, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise SearchProviderError(f"Ошибка сети при поиске (Yandex): {exc}") from exc

        if response.status_code >= 400:
            raise SearchProviderError(
                f"Yandex Search API вернул HTTP {response.status_code}: {response.text[:300]}"
            )

        data = response.json()
        raw_data = data.get("rawData")
        if not raw_data:
            raise SearchProviderError("Yandex Search API не вернул поле rawData")

        try:
            xml_text = base64.b64decode(raw_data).decode("utf-8")
        except Exception as exc:
            raise SearchProviderError(f"Не удалось декодировать rawData из Yandex Search API: {exc}") from exc

        return _parse_yandex_search_xml(xml_text, limit=max(1, limit))
