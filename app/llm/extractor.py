import json
from typing import Any, Dict, List, Optional, Type
from uuid import uuid4

from pydantic import ValidationError

from app.llm.client import LLMClient
from app.models import ScenarioDetailsDraft, ServiceOffer


class OfferExtractionError(Exception):
    """Ошибка извлечения или валидации предложения услуги из ответа LLM."""


class ScenarioExtractionError(Exception):
    """Ошибка извлечения деталей сценария из произвольного текста."""


_SYSTEM_PROMPT = """Ты извлекаешь структурированные данные о предложении услуги из текста.
Верни ТОЛЬКО валидный JSON-объект без пояснений и лишнего текста.

Правила:
1. Не додумывай отсутствующие сведения. Если в тексте нет цены, единицы расчёта, работ или условий — оставляй null или пустой список [].
2. Для pricing_unit и unit используй короткое каноническое обозначение единицы из текста (например: "fixed", "hour", "minute", "sqm", "unit", "month", "session", "km", "kg" или иную подходящую единицу из текста).
3. Для provider_type ставь "company" (фирма/студия/агентство), "private" (частный мастер/фрилансер/самозанятый) или "unknown", если из текста это неясно.
4. Поля JSON должны соответствовать схеме:
{
  "id": "string (можно сгенерировать короткий slug)",
  "provider_name": "string",
  "provider_type": "company" | "private" | "unknown",
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


def _parse_llm_json(raw_response: str, error_cls: Type[Exception]) -> Dict[str, Any]:
    cleaned = _strip_markdown_fences(raw_response)
    try:
        payload: Any = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise error_cls(f"LLM вернула некорректный JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise error_cls("Ожидался JSON-объект от LLM")
    return payload


def _dedupe_str_list(items: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for raw in items:
        cleaned = " ".join(raw.strip().split())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


_SCENARIO_SYSTEM_PROMPT = """Ты разбиваешь произвольное описание заказа услуги на атомарные структурные теги.
Верни ТОЛЬКО валидный JSON-объект без пояснений и лишнего текста.

Правила:
1. Не додумывай детали, которых нет в тексте клиента. Если чего-то нет — верни пустой список [].
2. Разбивай крупные задачи на короткие атомарные работы (2-4 слова каждая) в required_works.
3. Материалы, расходники и оборудование заказчика/исполнителя выделяй в required_components.
4. Особые требования (срочность, время суток, выезд за город, работа в выходные и т.п.) выноси в conditions.
5. Формат JSON:
{
  "required_works": ["string"],
  "required_components": ["string"],
  "conditions": ["string"]
}
"""


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
        payload = _parse_llm_json(raw_response, OfferExtractionError)

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


class ScenarioDetailsExtractor:
    """Извлекает атомарные работы, компоненты и условия из произвольного текста сценария."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract(
        self,
        raw_text: str,
        service_title: Optional[str] = None,
    ) -> ScenarioDetailsDraft:
        if not raw_text.strip():
            raise ScenarioExtractionError("Описание сценария пусто")

        user_prompt = (
            f"Услуга: {service_title.strip()}\nОписание клиента: {raw_text.strip()}"
            if service_title and service_title.strip()
            else raw_text.strip()
        )
        raw_response = self.client.complete(_SCENARIO_SYSTEM_PROMPT, user_prompt)
        payload = _parse_llm_json(raw_response, ScenarioExtractionError)

        try:
            draft = ScenarioDetailsDraft.model_validate(payload)
        except ValidationError as exc:
            raise ScenarioExtractionError(
                f"Ответ LLM не соответствует схеме ScenarioDetailsDraft: {exc}"
            ) from exc

        return ScenarioDetailsDraft(
            required_works=_dedupe_str_list(draft.required_works),
            required_components=_dedupe_str_list(draft.required_components),
            conditions=_dedupe_str_list(draft.conditions),
            needs_confirmation=True,
        )
