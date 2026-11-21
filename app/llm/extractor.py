import json
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import ValidationError

from app.llm.client import LLMClient
from app.models import ServiceOffer


class OfferExtractionError(Exception):
    """Ошибка извлечения или валидации предложения услуги из ответа LLM."""


_SYSTEM_PROMPT = """Ты извлекаешь структурированные данные о предложении услуги из текста.
Верни ТОЛЬКО валидный JSON-объект без пояснений и лишнего текста.

Правила:
1. Не додумывай отсутствующие сведения. Если в тексте нет цены, единицы расчёта, работ или условий — оставляй null или пустой список [].
2. Для pricing_unit и unit используй короткое каноническое обозначение единицы из текста (например: "fixed", "hour", "minute", "sqm", "unit", "month", "session", "km", "kg" или иную подходящую единицу из текста).
3. Поля JSON должны соответствовать схеме:
{
  "id": "string (можно сгенерировать короткий slug)",
  "provider_name": "string",
  "service_title": "string",
  "base_price": number | null,
  "pricing_unit": "string" | null,
  "included_works": ["string"],
  "included_components": ["string"],
  "exclusions_or_limits": ["string"],
  "surcharges": [
    {
      "name": "string",
      "amount": number,
      "unit": "string",
      "is_mandatory": boolean,
      "condition_description": "string" | null
    }
  ],
  "min_volume": number | null,
  "max_volume": number | null,
  "conditions": ["string"]
}
"""


def _strip_markdown_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


class OfferExtractor:
    """Извлекает модель ServiceOffer из произвольного текста через LLMClient."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract(
        self,
        raw_text: str,
        offer_id: Optional[str] = None,
        provider_name: Optional[str] = None,
    ) -> ServiceOffer:
        if not raw_text.strip():
            raise OfferExtractionError("Исходный текст предложения пуст")

        raw_response = self.client.complete(_SYSTEM_PROMPT, raw_text)
        cleaned = _strip_markdown_fences(raw_response)

        try:
            payload: Dict[str, Any] = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise OfferExtractionError(
                f"LLM вернула некорректный JSON: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise OfferExtractionError("Ожидался JSON-объект от LLM")

        if offer_id:
            payload["id"] = offer_id
        elif not payload.get("id"):
            payload["id"] = f"offer-{uuid4().hex[:8]}"

        if provider_name and not payload.get("provider_name"):
            payload["provider_name"] = provider_name

        try:
            return ServiceOffer.model_validate(payload)
        except ValidationError as exc:
            raise OfferExtractionError(
                f"Ответ LLM не соответствует схеме ServiceOffer: {exc}"
            ) from exc
