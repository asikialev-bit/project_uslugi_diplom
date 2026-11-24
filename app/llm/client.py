import os
from typing import Optional, Protocol

import httpx


class LLMConfigurationError(Exception):
    """Ошибка конфигурации внешнего LLM-провайдера."""


class LLMProviderError(Exception):
    """Ошибка сети или некорректный ответ внешнего LLM-провайдера."""


class LLMClient(Protocol):
    """Абстрактный интерфейс клиента языковой модели."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Отправляет промпт модели и возвращает текстовый ответ."""
        ...


class OpenAICompatibleLLMClient:
    """HTTP-клиент для OpenAI-совместимых Chat Completions API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key.strip():
            raise LLMConfigurationError("Не задан LLM_API_KEY")
        if not model.strip():
            raise LLMConfigurationError("Не задана модель LLM_MODEL")
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> "OpenAICompatibleLLMClient":
        """Создаёт клиент из переменных окружения."""
        api_key = os.getenv("LLM_API_KEY", "")
        model = os.getenv("LLM_MODEL", "")
        base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"LLM API вернул ошибку HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                f"Ошибка соединения с LLM API: {exc}"
            ) from exc
        except ValueError as exc:
            raise LLMProviderError(
                f"LLM API вернул некорректный JSON-ответ: {exc}"
            ) from exc

        choices = data.get("choices") or []
        if not choices:
            raise LLMProviderError("LLM вернула пустой список choices")
        content: Optional[str] = choices[0].get("message", {}).get("content")
        if not content:
            raise LLMProviderError("LLM вернула пустой текст ответа")
        return content
