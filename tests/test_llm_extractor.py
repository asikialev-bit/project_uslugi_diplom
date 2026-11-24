from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.llm import (
    OfferExtractionError,
    OfferExtractor,
    ScenarioDetailsExtractor,
    ScenarioExtractionError,
)
from app.main import app, get_offer_extractor, get_scenario_extractor, require_user


def _fake_user() -> dict[str, str]:
    return {"id": "user-test", "email": "test@example.com", "created_at": "2026-01-01"}


class FakeLLMClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self.response


def test_extract_offer_from_plain_json() -> None:
    json_response = """
    {
      "provider_name": "Клининг Плюс",
      "service_title": "Уборка офиса",
      "base_price": 120,
      "pricing_unit": "per_sqm",
      "included_works": ["мытьё полов"],
      "included_components": [],
      "exclusions_or_limits": [],
      "surcharges": [
        {
          "name": "Выезд",
          "amount": 500,
          "unit": "fixed",
          "is_mandatory": true,
          "condition_description": null
        }
      ],
      "min_volume": 20,
      "max_volume": null,
      "conditions": []
    }
    """
    extractor = OfferExtractor(FakeLLMClient(json_response))
    offer = extractor.extract("Уборка офиса 120 руб/кв.м, от 20 кв.м, выезд 500 руб")

    assert offer.id.startswith("offer-")
    assert offer.provider_name == "Клининг Плюс"
    assert offer.base_price == Decimal("120")
    assert offer.pricing_unit == "sqm"
    assert len(offer.surcharges) == 1


def test_extract_offer_strips_markdown_fences() -> None:
    fenced_response = """```json
    {
      "id": "custom-1",
      "provider_name": "Мастер",
      "service_title": "Покраска",
      "base_price": null,
      "pricing_unit": null
    }
    ```"""
    extractor = OfferExtractor(FakeLLMClient(fenced_response))
    offer = extractor.extract("Покраска стен, цена по договорённости")

    assert offer.id == "custom-1"
    assert offer.base_price is None
    assert offer.pricing_unit is None


def test_extract_offer_rejects_invalid_json() -> None:
    extractor = OfferExtractor(FakeLLMClient("Это просто текст, а не JSON"))

    with pytest.raises(OfferExtractionError):
        extractor.extract("Какой-то текст")


def test_extract_offer_rejects_invalid_schema() -> None:
    bad_schema_json = """
    {
      "provider_name": "Мастер",
      "service_title": "Покраска",
      "base_price": -100
    }
    """
    extractor = OfferExtractor(FakeLLMClient(bad_schema_json))

    with pytest.raises(OfferExtractionError):
        extractor.extract("Покраска -100 руб")


def test_api_extract_requires_auth() -> None:
    client = TestClient(app)
    response = client.post("/offers/extract", json={"raw_text": "Уборка 100 руб/кв.м"})
    assert response.status_code == 401


def test_api_extract_returns_503_when_llm_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    app.dependency_overrides[require_user] = _fake_user
    try:
        client = TestClient(app)
        response = client.post("/offers/extract", json={"raw_text": "Уборка 100 руб/кв.м"})
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_api_extract_returns_parsed_offer_with_override() -> None:
    fake_json = """
    {
      "service_title": "Генеральная уборка",
      "provider_type": "private",
      "base_price": 5000,
      "pricing_unit": "fixed"
    }
    """
    app.dependency_overrides[require_user] = _fake_user
    app.dependency_overrides[get_offer_extractor] = lambda: OfferExtractor(
        FakeLLMClient(fake_json)
    )
    try:
        client = TestClient(app)
        response = client.post(
            "/offers/extract",
            json={
                "raw_text": "Генеральная уборка 5000 руб",
                "offer_id": "o-ext-1",
                "provider_name": "Исполнитель Б",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "o-ext-1"
        assert data["provider_name"] == "Исполнитель Б"
        assert data["provider_type"] == "private"
        assert data["base_price"] == "5000"
    finally:
        app.dependency_overrides.clear()


def test_api_extract_returns_502_on_provider_error() -> None:
    from app.llm import LLMProviderError

    class BrokenLLMClient:
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            raise LLMProviderError("LLM API вернул ошибку HTTP 429")

    app.dependency_overrides[require_user] = _fake_user
    app.dependency_overrides[get_offer_extractor] = lambda: OfferExtractor(
        BrokenLLMClient()
    )
    try:
        client = TestClient(app)
        response = client.post("/offers/extract", json={"raw_text": "Услуга 1000 руб"})
        assert response.status_code == 502
        assert "429" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_scenario_details_extractor_deduplicates_and_requires_confirmation() -> None:
    response_json = """```json
    {
      "required_works": ["мытьё полов", "Мытьё   полов", "чистка санузла"],
      "required_components": ["эко-химия"],
      "conditions": ["срочно в день заказа", "вечернее время"]
    }
    ```"""
    extractor = ScenarioDetailsExtractor(FakeLLMClient(response_json))
    draft = extractor.extract(
        "Нужно помыть полы и санузел, своя эко-химия, срочно сегодня вечером",
        service_title="Уборка квартиры",
    )

    assert draft.needs_confirmation is True
    assert draft.required_works == ["мытьё полов", "чистка санузла"]
    assert draft.required_components == ["эко-химия"]
    assert draft.conditions == ["срочно в день заказа", "вечернее время"]


def test_scenario_details_extractor_rejects_empty_and_invalid_json() -> None:
    extractor = ScenarioDetailsExtractor(FakeLLMClient("не json"))
    with pytest.raises(ScenarioExtractionError):
        extractor.extract("   ")
    with pytest.raises(ScenarioExtractionError):
        extractor.extract("Нужна уборка")


def test_api_scenario_extract_details_requires_auth_and_returns_draft() -> None:
    client = TestClient(app)
    assert (
        client.post(
            "/scenarios/extract-details",
            json={"raw_text": "Помыть окна и балкон"},
        ).status_code
        == 401
    )

    app.dependency_overrides[require_user] = _fake_user
    app.dependency_overrides[get_scenario_extractor] = lambda: ScenarioDetailsExtractor(
        FakeLLMClient(
            '{"required_works": ["мойка окон", "уборка балкона"], "required_components": [], "conditions": []}'
        )
    )
    try:
        resp = client.post(
            "/scenarios/extract-details",
            json={
                "raw_text": "Помыть окна и балкон",
                "service_title": "Клининг",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["needs_confirmation"] is True
        assert data["required_works"] == ["мойка окон", "уборка балкона"]
    finally:
        app.dependency_overrides.clear()
