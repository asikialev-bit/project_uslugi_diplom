import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.llm import OfferExtractor
from app.main import app, get_offer_extractor


class _DemoLLMClient:
    """Мок LLM-клиента, возвращающий заранее подготовленные JSON-ответы по тексту."""

    def __init__(self, mapping: dict[str, dict]) -> None:
        self.mapping = mapping

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        for key, payload in self.mapping.items():
            if key in user_prompt:
                return json.dumps(payload, ensure_ascii=False)
        raise AssertionError(f"Неожиданный текст для извлечения: {user_prompt}")


def test_end_to_end_demo_scenario(tmp_path: Path, monkeypatch) -> None:
    """Сквозная проверка: извлечение -> сохранение -> сравнение в SQLite через API."""
    db_file = tmp_path / "e2e_demo.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    raw_texts = {
        "БыстроСтарт": (
            "Исполнитель БыстроСтарт: услуга по 1000 руб/час, минимум 5 часов. "
            "Входит аудит и настройка. Материалы включены. Выезд 500 руб обязательно, "
            "срочно в день заказа +1500 руб."
        ),
        "Студия Фикс": (
            "Студия Фикс: сделаем всё под ключ за 12000 руб (фиксированная цена). "
            "Входит аудит и настройка, материалы включены, условие: срочно."
        ),
        "БезЦенник": (
            "БезЦенник: аудит и настройка, цена по договорённости после звонка."
        ),
        "Ограниченный": (
            "Ограниченный: 900 руб/час, настройка не входит в услугу."
        ),
    }

    llm_responses = {
        "БыстроСтарт": {
            "id": "demo-1",
            "provider_name": "БыстроСтарт",
            "service_title": "Настройка под задачу",
            "base_price": 1000,
            "pricing_unit": "час",
            "included_works": ["аудит", "настройка"],
            "included_components": ["материалы"],
            "surcharges": [
                {
                    "name": "Выезд",
                    "amount": 500,
                    "unit": "fixed",
                    "is_mandatory": True,
                },
                {
                    "name": "Срочность",
                    "amount": 1500,
                    "unit": "fixed",
                    "is_mandatory": False,
                    "condition_description": "срочно",
                },
            ],
            "min_volume": 5,
        },
        "Студия Фикс": {
            "id": "demo-2",
            "provider_name": "Студия Фикс",
            "service_title": "Пакет под ключ",
            "base_price": 12000,
            "pricing_unit": "фикс",
            "included_works": ["аудит", "настройка"],
            "included_components": ["материалы"],
            "conditions": ["срочно"],
        },
        "БезЦенник": {
            "id": "demo-3",
            "provider_name": "БезЦенник",
            "service_title": "Консультация и настройка",
            "base_price": None,
            "pricing_unit": None,
            "included_works": ["аудит", "настройка"],
        },
        "Ограниченный": {
            "id": "demo-4",
            "provider_name": "Ограниченный",
            "service_title": "Только аудит",
            "base_price": 900,
            "pricing_unit": "hour",
            "included_works": ["аудит"],
            "exclusions_or_limits": ["настройка"],
        },
    }

    app.dependency_overrides[get_offer_extractor] = lambda: OfferExtractor(
        _DemoLLMClient(llm_responses)
    )
    client = TestClient(app)

    try:
        # 1. Извлекаем предложения из сырых текстов и сохраняем каждое в БД
        for raw_text in raw_texts.values():
            extract_resp = client.post("/offers/extract", json={"raw_text": raw_text})
            assert extract_resp.status_code == 200
            extracted_offer = extract_resp.json()

            save_resp = client.post("/offers", json=extracted_offer)
            assert save_resp.status_code == 200

        # 2. Создаём сценарий заказа клиента (10 часов, условие "срочно")
        scenario_payload = {
            "id": "demo-scen-1",
            "title": "Срочная настройка (10 часов)",
            "required_works": ["аудит", "настройка"],
            "volume": "10",
            "pricing_unit": "hour",
            "required_components": ["материалы"],
            "conditions": ["срочно"],
        }
        scen_resp = client.post("/scenarios", json=scenario_payload)
        assert scen_resp.status_code == 200

        # 3. Получаем итоговое объяснимое сравнение
        compare_resp = client.get("/scenarios/demo-scen-1/compare")
        assert compare_resp.status_code == 200
        results = compare_resp.json()
        assert len(results) == 4

        # Порядок: comparable (demo-1), partially_comparable с ценой (demo-2),
        # partially_comparable без цены (demo-3), not_comparable (demo-4)
        assert [r["offer_id"] for r in results] == [
            "demo-1",
            "demo-2",
            "demo-3",
            "demo-4",
        ]

        by_id = {r["offer_id"]: r for r in results}

        # БыстроСтарт: 10 * 1000 + 500 (выезд) + 1500 (срочность по условию) = 12000
        assert by_id["demo-1"]["status"] == "comparable"
        assert by_id["demo-1"]["completeness"] == "complete"
        assert by_id["demo-1"]["total_estimated_price"] == "12000"

        # Студия Фикс: fixed vs hour -> partially_comparable, цена 12000
        assert by_id["demo-2"]["status"] == "partially_comparable"
        assert by_id["demo-2"]["total_estimated_price"] == "12000"

        # БезЦенник: нет цены -> insufficient, но условие "срочно" тоже проверено
        assert by_id["demo-3"]["completeness"] == "insufficient"
        assert by_id["demo-3"]["total_estimated_price"] is None
        assert len(by_id["demo-3"]["missing_info"]) >= 3

        # Ограниченный: настройка в ограничениях -> not_comparable, но полнота проверена
        assert by_id["demo-4"]["status"] == "not_comparable"
        assert by_id["demo-4"]["completeness"] == "partial"
        assert by_id["demo-4"]["total_estimated_price"] is None
        assert any("ограничениях" in d for d in by_id["demo-4"]["differences"])
    finally:
        app.dependency_overrides.clear()
