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
| `app/main.py` | Точка входа FastAPI, маршруты REST API и статики | Реализованы `/`, `/workspace`, `/static/*`, `/health`, `/auth/*`, `/me`, `/me/company`, `/credits`, `/credits/topup` (dev), `/offers` (`GET`/`POST`/`DELETE`), `/offers/extract`, `/scenarios` (`GET`/`POST`/`DELETE`), `/scenarios/extract-details`, `/compare`, `/scenarios/{id}/compare`, `/scenarios/{id}/report`, `/scenarios/{id}/unlock` |
| `app/auth/` | Беспарольная авторизация по OTP-кодам на email и сессии | Реализованы `email_sender.py` (`ConsoleEmailSender`, `SMTPEmailSender`) и `service.py` (`AuthService`) |
| `app/models/` | Pydantic-модели предметной области и нормализация единиц | Реализованы `domain.py` (`ProviderType`, `SimilarityBreakdown`, `MarketSummary`, `OwnPositioning`, `ComparisonReportResponse`, `ScenarioDetailsDraft`) и `units.py` (`normalize_unit`, `get_unit_conversion_factor` на базе `Fraction`) |
| `app/rules/` | Правила сопоставимости, полноты данных и оценки сходства | Реализованы `matching.py`, `completeness.py`, `comparability.py`, `similarity.py` (45/30/15/10) и `evaluator.py` |
| `app/calculator/` | Расчёт стоимости, сводки рынка и серверное скрытие freemium | Реализован `pricing.py` (`calculate_comparison`, `compare_offers`, `build_comparison_report` с сегментацией `company`/`private`) |
| `app/storage/` | Изолированный слой работы с БД (SQLite) | Реализован `sqlite_repo.py` (`SQLiteRepository`: предложения, сценарии, пользователи, OTP-коды, сессии, профили компаний, `credit_ledger`, `scenario_unlocks`) |
| `app/llm/` | Извлечение структурированных данных из текстов через LLM | Реализованы `client.py` и `extractor.py` (`OfferExtractor`, `ScenarioDetailsExtractor`) |
| `app/discovery/` | Легальный поиск конкурентов и загрузка открытых прайс-страниц | Реализованы `providers.py` (`TavilySearchProvider`), `fetcher.py` (`PublicPageFetcher` с `robots.txt`) и `service.py` (`DiscoveryService`) |
| `frontend/` | Веб-интерфейс (обзорная страница и рабочий стол сравнения) | Реализованы `index.html`, `workspace.html` (модальный вход с размытием фона, компактный сценарий, профиль компании, сегментные фильтры), `styles.css`, `theme.js`, `motion.js`, `api.js`, `render.js`, `workspace.js` |
| `tests/` | Автоматические тесты (`pytest`) | Реализованы `test_health.py`, `test_models.py`, `test_rules.py`, `test_similarity.py`, `test_calculator.py`, `test_storage_and_api.py`, `test_llm_extractor.py`, `test_e2e_demo.py`, `test_frontend.py`, `test_auth_and_company.py`, `test_credits_and_report.py` |

## Кредиты, фримиум и оплата (Шаги 9.2–10)

- `credit_ledger` (`id`, `user_id`, `delta`, `reason`, `reference_id`, `created_at`) и `scenario_unlocks` (`user_id`, `scenario_id`, `unlocked_at`) — реализованы в Шаге 9.2б (стартовый баланс `0`, атомарное списание через `BEGIN IMMEDIATE`).
- `payments` (`id`, `user_id`, `amount`, `credits_granted`, `provider_payment_id`, `status`) — планируется в Шаге 10 вместе с модулем поиска живых конкурентов (`app/discovery/`).
