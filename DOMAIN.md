# DOMAIN.md

> Статус документа: **актуализирован по результатам Шага 3**. Описывает доменные сущности, независимые оси оценки (сопоставимость и полнота данных) и правила в `app/models/` и `app/rules/`.

## Единицы расчёта (`PricingUnit`)

- `fixed` — фиксированная цена за всю услугу;
- `per_hour` — за час работы;
- `per_unit` — за единицу (штуку, позицию);
- `per_sqm` — за квадратный метр.

## Две независимые оси оценки

Полнота данных и уровень сопоставимости оцениваются **раздельно**: например, предложение без цены (`insufficient`) всё равно может быть признано несопоставимым (`not_comparable`), если оно не подходит по объёму или ограничениям.

### 1. Статусы сопоставимости (`ComparabilityStatus`)

- `comparable` — предложение полностью подходит под сценарий и его можно сравнивать напрямую;
- `partially_comparable` — предложение можно сравнивать с оговорками (например, фиксированная цена при объёмном сценарии, неполное покрытие состава работ/компонентов или наличие условных доплат);
- `not_comparable` — предложение нельзя корректно сравнивать со сценарием (несовместимые единицы расчёта, выход за границы `min_volume`/`max_volume`, попадание обязательных работ или компонентов в `exclusions_or_limits`).

### 2. Полнота данных (`DataCompleteness`)

- `complete` — все ключевые сведения присутствуют;
- `partial` — критичные данные для расчёта есть, но отсутствуют уточняющие сведения (например, не описан состав работ, компоненты или условие необязательной доплаты);
- `insufficient` — отсутствуют критичные данные (`base_price` или `pricing_unit`), без которых расчёт стоимости невозможен.

## Сущности

### `Surcharge` (доплата)
- `name` — название доплаты;
- `amount` — размер доплаты (`Decimal >= 0`);
- `unit` — единица расчёта (`PricingUnit`, по умолчанию `fixed`);
- `is_mandatory` — обязательна ли доплата;
- `condition_description` — текстовое описание условия применения (опционально).

### `ServiceOffer` (предложение услуги)
- `id`, `provider_name`, `service_title`;
- `base_price` (`Decimal >= 0`, опционально);
- `pricing_unit` (`PricingUnit`, опционально);
- `included_works`, `included_components`, `exclusions_or_limits`;
- `surcharges` — список `Surcharge`;
- `min_volume`, `max_volume` — ограничения по объёму (`> 0`, при наличии обоих `max_volume >= min_volume`);
- `conditions` — условия выполнения.

### `OrderScenario` (сценарий заказа)
- `id`, `title`;
- `required_works`, `required_components`, `conditions`;
- `volume` (`Decimal > 0`) и `pricing_unit` (`PricingUnit`).

### `ComparisonResult` и `PriceLineItem` (результат сравнения)
- `offer_id`, `provider_name`;
- `status` (`ComparabilityStatus`) и `completeness` (`DataCompleteness`);
- `total_estimated_price` (`Decimal >= 0`, опционально);
- `price_breakdown` — список строк `PriceLineItem` (`label`, `amount`);
- `differences` — список причин отличий;
- `missing_info` — список недостающих сведений.
