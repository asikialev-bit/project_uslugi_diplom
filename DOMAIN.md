# DOMAIN.md

> Статус документа: **актуализирован после универсального рефакторинга**. Описывает доменные сущности, гибкие единицы расчёта, независимые оси оценки и работу с условиями заказа.

## Гибкие единицы расчёта и пересчёт (`app/models/units.py`)

Чтобы сервис не был привязан к конкретной отрасли, единица расчёта (`pricing_unit` / `unit`) — это **любая непустая строка**, которая нормализуется через словарь синонимов (например: `fixed`/`фикс`/`за проект` → `fixed`; `per_hour`/`час`/`ч` → `hour`; `per_sqm`/`кв.м`/`м2` → `sqm`; `per_unit`/`шт` → `unit`; произвольные единицы вроде `month`, `session`, `km` сохраняются в каноническом нижнем регистре).

Перевод объёма сценария в единицу предложения поддерживается двумя способами:
- встроенные точные физические переводы (`hour` ↔ `minute`, `km` ↔ `meter`, `kg` ↔ `gram`);
- явные коэффициенты `unit_conversions` в `OrderScenario` (например, `{"session": 8}` для пересчёта месяцев в занятия).

## Две независимые оси оценки

Полнота данных и уровень сопоставимости оцениваются **раздельно**: даже при несопоставимости (`not_comparable`) система продолжает проверку недостающих сведений и совместимости доплат.

### 1. Статусы сопоставимости (`ComparabilityStatus`)

- `comparable` — предложение полностью подходит под сценарий и его можно сравнивать напрямую;
- `partially_comparable` — предложение можно сравнивать с оговорками (фиксированная цена при объёмном сценарии, применённый пересчёт единиц, неполное покрытие работ/компонентов, неучтённые условия сценария или неактивированные условные доплаты);
- `not_comparable` — предложение нельзя корректно сравнивать со сценарием (несовместимые единицы без перевода, выход за границы `min_volume`/`max_volume`, попадание обязательных работ, компонентов или условий сценария в `exclusions_or_limits`).

### 2. Полнота данных (`DataCompleteness`)

- `complete` — все ключевые сведения присутствуют;
- `partial` — критичные данные для расчёта есть, но отсутствуют уточняющие сведения (не описан состав работ, компоненты, условие доплаты или не подтверждено влияние условия сценария);
- `insufficient` — отсутствуют критичные данные (`base_price` или `pricing_unit`), без которых расчёт стоимости невозможен.

## Учёт условий (`conditions`)

- Если условие из `OrderScenario.conditions` совпадает с ограничением из `ServiceOffer.exclusions_or_limits`, предложение становится `not_comparable`.
- Если условие сценария совпадает с описанием условной доплаты (`Surcharge.is_mandatory = False`), эта доплата **автоматически активируется и включается в расчёт цены**.
- Если условие сценария не упомянуто ни в `offer.conditions`, ни в `offer.surcharges`, это фиксируется как в `differences`, так и в `missing_info`.

## Сущности

### `Surcharge` (доплата)
- `name`, `amount` (`Decimal >= 0`), `unit` (`str`, по умолчанию `fixed`), `is_mandatory`, `condition_description`.

### `ServiceOffer` (предложение услуги)
- `id`, `provider_name`, `service_title`;
- `base_price` (`Decimal >= 0`, опционально), `pricing_unit` (`str`, опционально);
- `included_works`, `included_components`, `exclusions_or_limits`, `surcharges`, `min_volume`, `max_volume`, `conditions`.

### `OrderScenario` (сценарий заказа)
- `id`, `title`, `required_works`, `required_components`, `conditions`;
- `volume` (`Decimal > 0`), `pricing_unit` (`str`), `unit_conversions` (`Dict[str, Decimal]`).

### `ComparisonResult` и `PriceLineItem`
- `offer_id`, `provider_name`, `status`, `completeness`, `total_estimated_price`, `price_breakdown`, `differences`, `missing_info`.
