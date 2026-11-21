# TASKS.md

## Выполнено

- [x] **Шаг 1. Инициализация проекта и окружения**
  - Создана структура папок `app/` и `tests/`.
  - Подготовлена базовая документация (`README.md`, `PRODUCT.md`, `DOMAIN.md`, `ARCHITECTURE.md`, `TASKS.md`, `.env.example`).
  - Настроено окружение Python + FastAPI + Pydantic + pytest, добавлен маршрут `GET /health` и тест на него.
- [x] **Шаг 2. Доменные модели (`app/models/`)**
  - Определены Pydantic-модели для сценария заказа, предложения услуги, доплат, статусов сопоставимости, полноты данных и результата сравнения.
  - Актуализированы `DOMAIN.md` и `ARCHITECTURE.md`, добавлены тесты валидации в `tests/test_models.py`.
- [x] **Шаг 3. Правила сопоставимости и полноты данных (`app/rules/`)**
  - Реализованы независимые проверки полноты данных (`check_completeness`) и сопоставимости (`check_comparability`), а также единая точка вызова `evaluate_offer`.
  - Покрыты тестами в `tests/test_rules.py`, актуализированы `DOMAIN.md` и `ARCHITECTURE.md`.
- [x] **Шаг 4. Калькулятор стоимости (`app/calculator/`)**
  - Реализованы `calculate_comparison` и `compare_offers` с детализацией базовой цены и обязательных доплат, сохранением всех замечаний при несопоставимости или неполных данных и сортировкой результатов.
  - Покрыты тестами в `tests/test_calculator.py`, актуализирована `ARCHITECTURE.md`.
- [x] **Шаг 5. Слой хранения (`app/storage/`) и REST API (`app/main.py`)**
  - Реализован `SQLiteRepository` для хранения предложений и сценариев в SQLite.
  - Добавлены эндпоинты `/offers`, `/scenarios`, `/compare` и `/scenarios/{scenario_id}/compare`.
  - Покрыты тестами в `tests/test_storage_and_api.py`, актуализированы `README.md` и `ARCHITECTURE.md`.

## В очереди (предварительно)

- [ ] **Шаг 6. Извлечение данных через LLM (`app/llm/`)**
  - Продумать и реализовать парсер неструктурированного текста предложений в модель `ServiceOffer` с валидацией через Pydantic (и мок-тестами без реальных ключей).
