from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.llm import OfferExtractionError, OfferExtractor
from app.main import app, get_offer_extractor


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


def test_api_extract_returns_503_when_llm_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    client = TestClient(app)

    response = client.post("/offers/extract", json={"raw_text": "Уборка 100 руб/кв.м"})
    assert response.status_code == 503


def test_api_extract_returns_parsed_offer_with_override() -> None:
    fake_json = """
    {
      "service_title": "Генеральная уборка",
      "base_price": 5000,
      "pricing_unit": "fixed"
    }
    """
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
        assert data["base_price"] == "5000"
    finally:
        app.dependency_overrides.clear()
