from html.parser import HTMLParser
import re
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx


class FetchError(Exception):
    """Ошибка или запрет при загрузке публичной страницы."""


class _VisibleTextHTMLParser(HTMLParser):
    """Извлекает читаемый текст из HTML, отбрасывая скрипты и стили."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._chunks.append(text)

    def get_text(self) -> str:
        raw = "\n".join(self._chunks)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def extract_visible_text(html: str, max_chars: int = 12000) -> str:
    """Преобразует HTML в компактный читаемый текст для LLM-экстрактора."""
    parser = _VisibleTextHTMLParser()
    parser.feed(html)
    parser.close()
    text = parser.get_text()
    if len(text) > max_chars:
        return text[:max_chars].strip()
    return text


class PublicPageFetcher:
    """Безопасный загрузчик открытых HTML-страниц с проверкой robots.txt."""

    def __init__(
        self,
        timeout_seconds: float = 4.0,
        max_bytes: int = 512 * 1024,
        user_agent: str = "ServiceMatchBot/1.0",
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.user_agent = user_agent

    def _is_allowed_by_robots(self, client: httpx.Client, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            resp = client.get(robots_url, headers={"User-Agent": self.user_agent})
            if resp.status_code >= 400:
                return True
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp.can_fetch(self.user_agent, url)
        except httpx.HTTPError:
            return True

    def fetch_text(self, url: str) -> str:
        """Загружает публичную страницу и возвращает извлечённый текст."""
        with httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            if not self._is_allowed_by_robots(client, url):
                raise FetchError("Загрузка запрещена правилами robots.txt")

            try:
                response = client.get(
                    url,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "text/html,application/xhtml+xml,text/plain",
                    },
                )
            except httpx.HTTPError as exc:
                raise FetchError(f"Сетевая ошибка при загрузке страницы: {exc}") from exc

            if response.status_code in (401, 403, 429):
                raise FetchError(
                    f"Страница ограничила автоматический доступ (HTTP {response.status_code})"
                )
            if response.status_code >= 400:
                raise FetchError(f"Страница вернула HTTP {response.status_code}")

            content_type = response.headers.get("content-type", "").lower()
            if "html" not in content_type and "text/plain" not in content_type:
                raise FetchError(f"Неподдерживаемый тип контента: {content_type or 'unknown'}")

            raw_text = response.text[: self.max_bytes]
            lowered = raw_text.lower()
            if "captcha" in lowered or "cf-turnstile" in lowered or "g-recaptcha" in lowered:
                raise FetchError("Страница защищена проверкой CAPTCHA и пропущена")

            extracted = (
                raw_text.strip()
                if "text/plain" in content_type
                else extract_visible_text(raw_text)
            )
            if len(extracted) < 40:
                raise FetchError("На странице недостаточно текстовой информации")
            return extracted
