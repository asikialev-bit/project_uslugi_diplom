# ARCHITECTURE.md

## Технологический стек

- **Язык:** Python
- **API:** FastAPI
- **Валидация и схемы данных:** Pydantic
- **Хранение данных:** SQLite (через изолированный слой хранения для возможного перехода на PostgreSQL в будущем)
- **Фронтенд:** Чистый модульный HTML + CSS + ES Modules JS (`frontend/`), адаптивная светлая/тёмная тема
- **Тестирование:** pytest

## Разделение модулей

Бизнес-логика не должна смешиваться с кодом API/интерфейса. В проекте заложена следующая структура:

| Модуль | Ответственность | Текущее состояние |
| --- | --- | --- |
| `app/main.py` | Точка входа FastAPI, маршруты REST API и статики | Реализованы `/`, `/workspace`, `/static/*`, `/health`, `/offers`, `/offers/extract`, `/scenarios`, `/compare`, `/scenarios/{id}/compare` |
| `app/models/` | Pydantic-модели предметной области и нормализация единиц | Реализованы `domain.py` и `units.py` (`normalize_unit`, `get_unit_conversion_factor`) |
| `app/rules/` | Правила сопоставимости и проверки полноты данных | Реализованы `completeness.py`, `comparability.py` и `evaluator.py` |
| `app/calculator/` | Расчёт итоговой стоимости с переводом единиц и активацией условных доплат | Реализован `pricing.py` (`calculate_comparison`, `compare_offers`) |
| `app/storage/` | Изолированный слой работы с БД (SQLite) | Реализован `sqlite_repo.py` (`SQLiteRepository`, `resolve_db_path`) |
| `app/llm/` | Извлечение структурированных данных из текстов через LLM | Реализованы `client.py` и `extractor.py` (`OfferExtractor`) |
| `frontend/` | Веб-интерфейс (обзорная страница и рабочий стол сравнения) | Реализованы `index.html`, `workspace.html`, `styles.css`, `theme.js`, `motion.js`, `api.js`, `render.js`, `workspace.js` |
| `tests/` | Автоматические тесты (`pytest`) | Реализованы `test_health.py`, `test_models.py`, `test_rules.py`, `test_calculator.py`, `test_storage_and_api.py`, `test_llm_extractor.py`, `test_e2e_demo.py`, `test_frontend.py` |

## Будущее расширение: аккаунты и кредиты (запланировано на Шаг 9)

Для коммерческой модели предусмотрено расширение слоя хранения и API:
- `users` (`id`, `email`, `password_hash`, `created_at`) — учётные записи пользователей.
- `credit_ledger` (`id`, `user_id`, `delta`, `reason`, `created_at`) — журнал операций начисления и списания кредитов (в первую очередь за вызов платного LLM-извлечения).
- `payments` (`id`, `user_id`, `amount`, `credits_granted`, `provider_payment_id`, `status`) — история оплат с проверкой подписи вебхуков платёжного шлюза.
