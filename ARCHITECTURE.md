# ARCHITECTURE.md

## Технологический стек

- **Язык:** Python
- **API:** FastAPI
- **Валидация и схемы данных:** Pydantic
- **Хранение данных:** SQLite (через изолированный слой хранения для возможного перехода на PostgreSQL в будущем)
- **Тестирование:** pytest

## Разделение модулей

Бизнес-логика не должна смешиваться с кодом API/интерфейса. В пакете `app/` заложена следующая структура:

| Модуль | Ответственность | Текущее состояние |
| --- | --- | --- |
| `app/main.py` | Точка входа FastAPI, маршруты REST API | Реализованы `/health`, `/offers`, `/offers/extract`, `/scenarios`, `/compare`, `/scenarios/{id}/compare` |
| `app/models/` | Pydantic-модели предметной области и нормализация единиц | Реализованы `domain.py` (`ComparabilityStatus`, `DataCompleteness`, `Surcharge`, `ServiceOffer`, `OrderScenario`, `PriceLineItem`, `ComparisonResult`) и `units.py` (`normalize_unit`, `get_unit_conversion_factor`) |
| `app/rules/` | Правила сопоставимости и проверки полноты данных | Реализованы `completeness.py`, `comparability.py` (включая матчинг `conditions`) и `evaluator.py` |
| `app/calculator/` | Расчёт итоговой стоимости с переводом единиц и активацией условных доплат | Реализован `pricing.py` (`calculate_comparison`, `compare_offers`) |
| `app/storage/` | Изолированный слой работы с БД (SQLite) | Реализован `sqlite_repo.py` (`SQLiteRepository`, `resolve_db_path`) |
| `app/llm/` | Извлечение структурированных данных из текстов через LLM | Реализованы `client.py` (`LLMClient`, `OpenAICompatibleLLMClient`) и `extractor.py` (`OfferExtractor`) |
| `tests/` | Автоматические тесты (`pytest`) | Реализованы `test_health.py`, `test_models.py`, `test_rules.py`, `test_calculator.py`, `test_storage_and_api.py`, `test_llm_extractor.py` |
