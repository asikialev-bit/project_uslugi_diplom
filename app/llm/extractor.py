from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any, Dict, List, Optional, Type
from uuid import uuid4

from pydantic import ValidationError

from app.llm.client import LLMClient, LLMProviderError
from app.models import (
    FIXED_UNIT,
    OrderScenario,
    ProviderType,
    ScenarioDetailsDraft,
    ServiceOffer,
    get_unit_conversion_factor,
    normalize_unit,
)


class OfferExtractionError(Exception):
    """Ошибка извлечения или валидации предложения услуги из ответа LLM."""


class ScenarioExtractionError(Exception):
    """Ошибка извлечения деталей сценария из произвольного текста."""


_SYSTEM_PROMPT = """Ты извлекаешь структурированные данные о предложении услуги из текста.
Верни ТОЛЬКО валидный JSON-объект без пояснений и лишнего текста.

Правила:
1. Не додумывай отсутствующие сведения. Если в тексте нет цены, единицы расчёта, работ или условий — оставляй null или пустой список [].
2. Для pricing_unit и unit используй короткое каноническое обозначение единицы из текста (например: "fixed", "hour", "minute", "sqm", "room", "unit", "month", "session", "km", "kg").
3. Для provider_type ставь "company" (фирма/студия/агентство), "private" (частный мастер/фрилансер/самозанятый) или "unknown", если из текста это неясно.
4. Если в тексте есть несколько разных тарифов/видов услуг (например: поддерживающая, после ремонта, генеральная), выбери цену ИМЕННО для целевой услуги в base_price; остальные тарифы НЕ добавляй в surcharges. В surcharges включай только дополнительные опции к основной услуге (выезд, срочность, мытьё духовки и т.п.).
5. Табличные строки вида "Услуга ;;;; 1500р" или "Сборка ПК — от 2000 руб." распознавай как базовую цену услуги. Если на странице продаются только готовые товары (например, готовые компьютеры за 100 000+ ₽ вместо услуги сборки), а цена самой услуги не указана — оставляй base_price = null, НЕ ставь цену товара в услугу.
6. Игнорируй рекламные проценты ("от 15%", "скидка 10%"), копеечные/маркетинговые числа (например, "от 15 руб." за мелкий болтик/мин) и авансы. Если реальная цена основной услуги не ясна — ставь base_price = null.
7. Поля JSON должны соответствовать схеме:
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
        target_service: Optional[str] = None,
    ) -> ServiceOffer:
        if not raw_text.strip():
            raise OfferExtractionError("Исходный текст предложения пуст")

        prompt_text = (
            f"Целевая услуга для поиска цены: {target_service.strip()}\n\n{raw_text}"
            if target_service and target_service.strip()
            else raw_text
        )
        raw_response = self.client.complete(_SYSTEM_PROMPT, prompt_text)
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


_UNIT_TOKEN_MAP = {
    "кв.м": "sqm",
    "кв м": "sqm",
    "м2": "sqm",
    "м²": "sqm",
    "sqm": "sqm",
    "комн": "room",
    "комната": "room",
    "комнаты": "room",
    "комнат": "room",
    "комнату": "room",
    "room": "room",
    "час": "hour",
    "ч": "hour",
    "hour": "hour",
    "мин": "minute",
    "минут": "minute",
    "шт": "unit",
    "мес": "month",
    "месяц": "month",
    "сеанс": "session",
    "заказ": "fixed",
    "квартиру": "fixed",
    "услугу": "fixed",
    "услуги": "fixed",
}

_PRICE_PATTERN = re.compile(
    r"(?:от\s*)?(\d[\d\s]{1,9})\s*(?:₽|руб\.?|р\.?)\s*(?:[\/за]+\s*(кв\.?\s*м|м2|м²|комнат[ауы]?|комн\.?|час|ч|минут[аы]?|мин|шт|месяц|мес|сеанс|заказ|квартиру|услуг[уи]))?",
    re.IGNORECASE,
)


class RuleBasedOfferExtractor:
    """Локальный детерминированный экстрактор предложения без вызова LLM."""

    def extract(
        self,
        raw_text: str,
        offer_id: Optional[str] = None,
        provider_name: Optional[str] = None,
        service_title: Optional[str] = None,
        hint_works: Optional[List[str]] = None,
        provider_type: ProviderType = ProviderType.UNKNOWN,
    ) -> ServiceOffer:
        text = " ".join(raw_text.split())
        if not text:
            raise OfferExtractionError("Исходный текст предложения пуст")

        base_price: Optional[Decimal] = None
        pricing_unit: Optional[str] = None
        for match in _PRICE_PATTERN.finditer(text):
            digits = match.group(1).replace(" ", "")
            try:
                candidate = Decimal(digits)
            except InvalidOperation:
                continue
            raw_unit = (match.group(2) or "").lower().strip()
            cleaned_unit = raw_unit.replace(".", " ").strip()
            unit_norm = _UNIT_TOKEN_MAP.get(raw_unit) or _UNIT_TOKEN_MAP.get(
                cleaned_unit, "fixed"
            )
            # Отбрасываем рекламные/случайные копеечные числа для фиксированных услуг
            if candidate <= 0 or (unit_norm == "fixed" and candidate < Decimal("150")):
                continue
            if unit_norm == "sqm" and candidate < Decimal("30"):
                continue
            base_price = candidate
            pricing_unit = unit_norm
            break

        lowered = text.lower()
        included_works = [
            w for w in (hint_works or []) if w.strip() and w.strip().lower() in lowered
        ]
        conditions = [
            marker
            for marker in ("срочно", "онлайн", "выезд", "круглосуточно")
            if marker in lowered
        ]

        return ServiceOffer(
            id=offer_id or f"rule-{uuid4().hex[:8]}",
            provider_name=(provider_name or "Исполнитель").strip(),
            provider_type=provider_type,
            service_title=(service_title or provider_name or "Услуга").strip(),
            base_price=base_price,
            pricing_unit=pricing_unit,
            included_works=included_works,
            conditions=conditions,
        )


_FALLBACK_CONVERSIONS: Dict[tuple, Decimal] = {
    ("fixed", "sqm"): Decimal("50"),
    ("fixed", "room"): Decimal("2"),
    ("fixed", "hour"): Decimal("4"),
    ("fixed", "minute"): Decimal("240"),
    ("sqm", "room"): Decimal("0.04"),
    ("sqm", "hour"): Decimal("0.0833"),
    ("room", "sqm"): Decimal("25"),
    ("room", "hour"): Decimal("2.5"),
    ("hour", "sqm"): Decimal("12"),
    ("hour", "room"): Decimal("0.4"),
}

_CONVERSION_SYSTEM_PROMPT = """Ты оцениваешь реалистичные коэффициенты пересчёта единиц измерения услуги для сопоставления цен.
Верни ТОЛЬКО валидный JSON-объект вида {"<target_unit>": number} без пояснений.
Правило: multiplier — это число, на которое нужно умножить объём сценария (scenario_volume), чтобы получить эквивалентный объём в целевой единице.
Пример: для уборки квартиры объёмом 60 sqm эквивалент в room ≈ 2.4 (multiplier = 0.04), в hour ≈ 5 (multiplier = 0.0833)."""


class UnitConversionEstimator:
    """Подбирает оценочные коэффициенты перевода несовместимых единиц (LLM + эвристики)."""

    def __init__(self, client: Optional[LLMClient] = None) -> None:
        self.client = client

    def estimate_conversions(
        self,
        scenario: OrderScenario,
        target_units: List[str],
    ) -> Dict[str, Decimal]:
        missing: List[str] = []
        for raw_unit in target_units:
            if not raw_unit:
                continue
            norm = normalize_unit(raw_unit)
            if norm == FIXED_UNIT or norm == scenario.pricing_unit:
                continue
            if (
                get_unit_conversion_factor(
                    scenario.pricing_unit, norm, scenario.unit_conversions
                )
                is None
                and norm not in missing
            ):
                missing.append(norm)

        if not missing:
            return {}

        estimated: Dict[str, Decimal] = {}
        if self.client is not None:
            user_prompt = (
                f"Услуга: {scenario.title}\n"
                f"Объём сценария: {scenario.volume} {scenario.pricing_unit}\n"
                f"Нужны коэффициенты для единиц: {', '.join(missing)}"
            )
            try:
                raw = self.client.complete(_CONVERSION_SYSTEM_PROMPT, user_prompt)
                payload = _parse_llm_json(raw, OfferExtractionError)
                for unit in missing:
                    val = payload.get(unit)
                    if val is not None:
                        dec = Decimal(str(val))
                        if Decimal("0") < dec <= Decimal("10000"):
                            estimated[unit] = dec
            except (OfferExtractionError, LLMProviderError, InvalidOperation, ValueError):
                pass

        for unit in missing:
            if unit not in estimated:
                fallback = _FALLBACK_CONVERSIONS.get((scenario.pricing_unit, unit))
                if fallback is not None:
                    estimated[unit] = fallback

        return estimated
