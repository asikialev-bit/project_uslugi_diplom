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
- [x] **Шаг 6. Извлечение данных через LLM (`app/llm/`)**
  - Реализован `OpenAICompatibleLLMClient`, `OfferExtractor` со строгой валидацией через Pydantic и эндпоинт `POST /offers/extract`.
  - Покрыты мок-тестами в `tests/test_llm_extractor.py`, актуализированы `.env.example` и `ARCHITECTURE.md`.
- [x] **Шаг 6.1. Универсальный рефакторинг (независимость от отрасли)**
  - Жёсткий `PricingUnit` Enum заменён на гибкие строковые единицы с нормализацией и пересчётом (`app/models/units.py`, `unit_conversions`).
  - Добавлена проверка условий заказа (`conditions`): учёт в `differences`/`missing_info` и автоматическая активация подходящих условных доплат в калькуляторе.
  - Обновлены промпт LLM, тесты и документация.

- [x] **Шаг 7. Демонстрационные данные и сквозной сценарий**
  - Реализован сквозной тест `tests/test_e2e_demo.py`, проверяющий полную цепочку: извлечение через `/offers/extract` -> сохранение в SQLite (`/offers`, `/scenarios`) -> объяснимое сравнение (`/scenarios/{id}/compare`).

- [x] **Шаг 8. Фронтенд / веб-интерфейс (`frontend/`)**
  - Реализованы две страницы: `/` (обзорная страница с живым примером «На витрине» / «В реальности» и шторкой) и `/workspace` (пошаговый рабочий стол сравнения).
  - Настроена адаптивная светлая/тёмная палитра (вычитание тоном без обводок), подключена раздача через FastAPI и добавлен тест `tests/test_frontend.py`.
- [x] **Шаг 8.1. UX-доработка рабочего стола (`/workspace`)**
  - Добавлены загрузка сохранённых сценариев и предложений из архива SQLite, редактирование добавленных/извлечённых предложений на месте и копирование списка вопросов подрядчику в буфер обмена.
- [x] **Шаг 8.2. Доработки по итогам ревью (бэкенд и фронтенд)**
  - Исправлены расчёты переводов на `Fraction`, пропуск ложных ошибок объёма при несовместимых единицах, общая логика `matching.py`, автозагрузка `.env`, обработка сетевых ошибок LLM (`502`) и `DELETE`-эндпоинты архива.
  - Во фронтенде добавлено экранирование атрибутов доплат, защита от двойного клика при копировании, обновление `meta[theme-color]` и сохранение уникального ID сценария.

- [x] **Шаг 9.1. Пользователи, вход по email-коду (OTP) и профиль своей компании**
  - Добавлены таблицы `users`, `auth_codes`, `sessions`, `company_profiles` в `SQLiteRepository`.
  - Реализованы `app/auth/` (`ConsoleEmailSender` для dev и `SMTPEmailSender` для реального SMTP через `.env`), защита OTP (SHA-256 HMAC, TTL 10 минут, лимит 5 попыток), маршруты `/auth/*`, `/me`, `/me/company` и автодобавление предложения своей компании в сравнение (`is_own_company`).
  - Покрыто тестами в `tests/test_auth_and_company.py`, обновлены `.env.example` и `ARCHITECTURE.md`.

- [x] **Шаг 9.2а. Многометрическая оценка сходства и гео/формат**
  - Добавлены поля `city`, `is_online`, `source_url` в модели, `SimilarityBreakdown` / `similarity_score` в `ComparisonResult`.
  - Реализован модуль `app/rules/similarity.py` (45% покрытие работ и состава по 4 состояниям + точность масштаба, 30% прозрачность прайса по 4 сигналам, 15% гео/формат, 10% единицы/объём) и общие проверки в `app/rules/matching.py`.
  - Покрыто тестами в `tests/test_similarity.py`.
- [x] **Шаг 9.2б. Журнал кредитов, отчёт и серверный freemium-фильтр**
  - Добавлены таблицы `credit_ledger` (стартовый баланс 0, атомарное списание через `BEGIN IMMEDIATE`) и `scenario_unlocks` в `SQLiteRepository`.
  - Реализованы `MarketSummary`, `OwnPositioning`, `ComparisonReportResponse` и серверная маскировка скрытых конкурентов (`build_comparison_report`), маршруты `/credits`, `/credits/topup` (dev-only), `/scenarios/{id}/report`, `/scenarios/{id}/unlock` и защита `/offers/extract` авторизацией.
  - Покрыто тестами в `tests/test_credits_and_report.py`.

- [x] **Шаг 9.2в. Гибридная форма сценария (обязательные поля + LLM-разбор произвольного текста на подтверждение)**
  - Добавлена модель `ScenarioDetailsDraft`, экстрактор `ScenarioDetailsExtractor` и защищённый маршрут `POST /scenarios/extract-details` для извлечения `required_works`, `required_components` и `conditions` с флагом `needs_confirmation=True`.
  - Покрыто тестами в `tests/test_llm_extractor.py`.

- [x] **Шаг 9.3. Интерфейс входа, «Моей компании», баланса кредитов и freemium/платного отчёта**
  - В `/workspace` (`frontend/workspace.html`, `api.js`, `render.js`, `workspace.js`, `styles.css`) подключены вход по email-коду, профиль «Моей компании», гибридная форма сценария с подтверждением LLM-тегов, баланс кредитов, freemium-превью со скрытыми карточками и полный отчёт со сводкой рынка и позиционированием.

## В очереди (предварительно)
- [ ] **Шаг 10. Поиск живых конкурентов и платёжный шлюз**
  - Легальный discovery/сбор конкурентов в `unlock`-пайплайне (без вызова LLM до оплаты), таблица `payments`, платёжный шлюз и IP rate limiting / CAPTCHA перед публичным запуском.
