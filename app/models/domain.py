from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.units import FIXED_UNIT, normalize_unit


def _clean_optional_str(value: Optional[str]) -> Optional[str]:
    """Удаляет лишние пробелы и превращает пустые строки в None."""
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return value


class ComparabilityStatus(str, Enum):
    """Статус сопоставимости предложения со сценарием заказа."""

    COMPARABLE = "comparable"
    PARTIALLY_COMPARABLE = "partially_comparable"
    NOT_COMPARABLE = "not_comparable"


class DataCompleteness(str, Enum):
    """Полнота сведений в предложении для оценки и расчёта."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class ProviderType(str, Enum):
    """Сегмент исполнителя: компания или частный мастер."""

    COMPANY = "company"
    PRIVATE = "private"
    UNKNOWN = "unknown"


class Surcharge(BaseModel):
    """Доплата или надбавка к базовой цене услуги."""

    name: str = Field(..., min_length=1, description="Название доплаты")
    amount: Decimal = Field(..., ge=0, description="Размер доплаты")
    unit: str = Field(
        default=FIXED_UNIT,
        description="Единица расчёта доплаты (fixed, hour, sqm, session и т.д.)",
    )
    is_mandatory: bool = Field(
        default=True,
        description="Является ли доплата обязательной по умолчанию",
    )
    condition_description: Optional[str] = Field(
        default=None,
        description="Условие, при котором применяется доплата",
    )

    @field_validator("unit")
    @classmethod
    def validate_and_normalize_unit(cls, value: str) -> str:
        return normalize_unit(value)


class ServiceOffer(BaseModel):
    """Предложение услуги от конкретного исполнителя."""

    id: str = Field(..., min_length=1, description="Уникальный идентификатор предложения")
    provider_name: str = Field(..., min_length=1, description="Название исполнителя")
    service_title: str = Field(..., min_length=1, description="Название услуги у исполнителя")
    base_price: Optional[Decimal] = Field(
        default=None,
        ge=0,
        description="Базовая цена; None означает, что цена не указана",
    )
    pricing_unit: Optional[str] = Field(
        default=None,
        description="Единица расчёта базовой цены; None, если не указана",
    )
    included_works: List[str] = Field(
        default_factory=list,
        description="Работы, входящие в базовую стоимость",
    )
    included_components: List[str] = Field(
        default_factory=list,
        description="Материалы или компоненты, включённые в цену",
    )
    exclusions_or_limits: List[str] = Field(
        default_factory=list,
        description="Ограничения и работы/условия, которые точно не входят",
    )
    surcharges: List[Surcharge] = Field(
        default_factory=list,
        description="Список известных доплат",
    )
    min_volume: Optional[Decimal] = Field(
        default=None,
        gt=0,
        description="Минимальный допустимый объём заказа",
    )
    max_volume: Optional[Decimal] = Field(
        default=None,
        gt=0,
        description="Максимальный допустимый объём заказа",
    )
    conditions: List[str] = Field(
        default_factory=list,
        description="Условия выполнения услуги",
    )
    city: Optional[str] = Field(
        default=None,
        description="Город оказания услуги",
    )
    is_online: bool = Field(
        default=False,
        description="Оказывается ли услуга дистанционно / онлайн",
    )
    source_url: Optional[str] = Field(
        default=None,
        description="Ссылка на источник или страницу прайса",
    )
    provider_type: ProviderType = Field(
        default=ProviderType.UNKNOWN,
        description="Тип исполнителя: компания, частный исполнитель или не определён",
    )

    @field_validator("city", "source_url", mode="before")
    @classmethod
    def normalize_optional_strings(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_str(value)

    @field_validator("pricing_unit")
    @classmethod
    def validate_and_normalize_unit(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return normalize_unit(value)

    @model_validator(mode="after")
    def validate_volume_bounds(self) -> "ServiceOffer":
        if (
            self.min_volume is not None
            and self.max_volume is not None
            and self.max_volume < self.min_volume
        ):
            raise ValueError("max_volume не может быть меньше min_volume")
        return self


class OrderScenario(BaseModel):
    """Сценарий заказа клиента, под который сравниваются предложения."""

    id: str = Field(..., min_length=1, description="Идентификатор сценария")
    title: str = Field(..., min_length=1, description="Краткое название сценария")
    required_works: List[str] = Field(
        default_factory=list,
        description="Обязательный состав работ для выполнения сценария",
    )
    volume: Decimal = Field(
        default=Decimal("1"),
        gt=0,
        description="Требуемый объём работ",
    )
    pricing_unit: str = Field(
        default=FIXED_UNIT,
        description="Единица измерения объёма в сценарии",
    )
    required_components: List[str] = Field(
        default_factory=list,
        description="Компоненты/материалы, которые должны быть включены",
    )
    conditions: List[str] = Field(
        default_factory=list,
        description="Дополнительные условия заказа",
    )
    unit_conversions: Dict[str, Decimal] = Field(
        default_factory=dict,
        description="Коэффициенты перевода объёма сценария в единицы предложений",
    )
    city: Optional[str] = Field(
        default=None,
        description="Целевой город оказания услуги",
    )
    is_online: bool = Field(
        default=False,
        description="Допустимо ли онлайн-оказание услуги",
    )

    @field_validator("city", mode="before")
    @classmethod
    def normalize_optional_city(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_str(value)

    @field_validator("pricing_unit")
    @classmethod
    def validate_and_normalize_unit(cls, value: str) -> str:
        return normalize_unit(value)

    @field_validator("unit_conversions")
    @classmethod
    def validate_unit_conversions(
        cls, value: Dict[str, Decimal]
    ) -> Dict[str, Decimal]:
        normalized: Dict[str, Decimal] = {}
        for unit_name, factor in value.items():
            if factor <= 0:
                raise ValueError("Коэффициент перевода единиц должен быть больше 0")
            normalized[normalize_unit(unit_name)] = factor
        return normalized


class PriceLineItem(BaseModel):
    """Отдельная строка в детализации расчёта стоимости."""

    label: str = Field(..., min_length=1, description="Пояснение к статье расхода")
    amount: Decimal = Field(..., ge=0, description="Рассчитанная сумма")


class SimilarityFactor(BaseModel):
    """Детализация одного фактора оценки сходства предложения и сценария."""

    score: int = Field(..., ge=0, le=100, description="Оценка фактора от 0 до 100")
    weight: int = Field(..., ge=0, le=100, description="Вес фактора в процентах")
    weighted_contribution: Decimal = Field(
        ...,
        ge=0,
        le=100,
        description="Вклад фактора в итоговый взвешенный индекс",
    )
    details: List[str] = Field(
        default_factory=list,
        description="Пояснения, из чего сложилась оценка фактора",
    )


class SimilarityBreakdown(BaseModel):
    """Многометрическая разбивка сходства услуги и прозрачности прайса (45/30/15/10)."""

    scope_coverage: SimilarityFactor = Field(
        ...,
        description="Покрытие обязательных работ, компонентов и соответствие масштабу (45%)",
    )
    price_transparency: SimilarityFactor = Field(
        ...,
        description="Полнота и прозрачность ценовых условий прайса (30%)",
    )
    geo_and_format: SimilarityFactor = Field(
        ...,
        description="Соответствие города и формата оказания услуги (15%)",
    )
    unit_and_volume: SimilarityFactor = Field(
        ...,
        description="Совместимость единиц измерения и границ объёма (10%)",
    )


class ComparisonResult(BaseModel):
    """Объяснимый результат сопоставления предложения со сценарием."""

    offer_id: str = Field(..., min_length=1, description="ID оцениваемого предложения")
    provider_name: str = Field(..., min_length=1, description="Название исполнителя")
    is_own_company: bool = Field(
        default=False,
        description="Является ли предложение предложением своей компании пользователя",
    )
    is_locked: bool = Field(
        default=False,
        description="Скрыты ли детали предложения до оплаты отчёта",
    )
    provider_type: ProviderType = Field(
        default=ProviderType.UNKNOWN,
        description="Тип исполнителя (скрывается как unknown в заблокированных карточках)",
    )
    status: ComparabilityStatus = Field(..., description="Статус сопоставимости")
    completeness: DataCompleteness = Field(..., description="Полнота исходных сведений")
    similarity_score: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Итоговый взвешенный индекс сходства от 0 до 100%",
    )
    similarity_breakdown: Optional[SimilarityBreakdown] = Field(
        default=None,
        description="Разбивка индекса сходства по 4 факторам",
    )
    total_estimated_price: Optional[Decimal] = Field(
        default=None,
        ge=0,
        description="Итоговая расчётная стоимость для сценария, если её можно вычислить",
    )
    price_breakdown: List[PriceLineItem] = Field(
        default_factory=list,
        description="Детализация стоимости по статьям",
    )
    differences: List[str] = Field(
        default_factory=list,
        description="Чем обусловлены отличия от сценария или других предложений",
    )
    missing_info: List[str] = Field(
        default_factory=list,
        description="Каких сведений не хватает для достоверного вывода",
    )


class SegmentSummary(BaseModel):
    """Ценовая сводка по отдельному сегменту исполнителей (компании / частники)."""

    provider_type: ProviderType
    total_offers_found: int = Field(..., ge=0)
    comparable_offers_count: int = Field(..., ge=0)
    min_price: Optional[Decimal] = Field(default=None, ge=0)
    median_price: Optional[Decimal] = Field(default=None, ge=0)
    max_price: Optional[Decimal] = Field(default=None, ge=0)


class MarketSummary(BaseModel):
    """Агрегированная сводка по рынку для оплаченного отчёта."""

    total_offers_found: int = Field(..., ge=0, description="Всего оценено конкурентов")
    comparable_offers_count: int = Field(
        ..., ge=0, description="Число сопоставимых конкурентов с расчётной ценой"
    )
    min_price: Optional[Decimal] = Field(
        default=None, ge=0, description="Минимальная расчётная цена среди конкурентов"
    )
    median_price: Optional[Decimal] = Field(
        default=None, ge=0, description="Медианная расчётная цена среди конкурентов"
    )
    max_price: Optional[Decimal] = Field(
        default=None, ge=0, description="Максимальная расчётная цена среди конкурентов"
    )
    segments: Dict[str, SegmentSummary] = Field(
        default_factory=dict,
        description="Разбивка сводки по сегментам (company / private)",
    )


class OwnPositioning(BaseModel):
    """Позиционирование компании пользователя относительно рынка."""

    offer_id: str = Field(..., min_length=1)
    own_provider_type: ProviderType = Field(default=ProviderType.UNKNOWN)
    own_price: Optional[Decimal] = Field(default=None, ge=0)
    price_rank: Optional[int] = Field(
        default=None,
        ge=1,
        description="Позиция компании по цене (1 — самое выгодное предложение)",
    )
    ranked_offers_count: int = Field(
        default=0, ge=0, description="Сколько предложений участвует в ценовом рейтинге"
    )
    diff_from_median_amount: Optional[Decimal] = Field(
        default=None,
        description="Отклонение своей цены от медианы рынка в рублях (отрицательное — дешевле)",
    )
    diff_from_median_percent: Optional[Decimal] = Field(
        default=None,
        description="Отклонение своей цены от медианы рынка в процентах",
    )
    segment_price_rank: Optional[int] = Field(
        default=None,
        ge=1,
        description="Позиция по цене внутри своего сегмента (компании или частники)",
    )
    segment_ranked_count: int = Field(
        default=0,
        ge=0,
        description="Сколько предложений в своём сегменте участвуют в рейтинге",
    )
    segment_diff_from_median_percent: Optional[Decimal] = Field(
        default=None,
        description="Отклонение от медианы своего сегмента в процентах",
    )
    segment_summary_text: Optional[str] = Field(
        default=None,
        description="Пояснение позиции внутри своего сегмента",
    )
    own_similarity_score: int = Field(default=0, ge=0, le=100)
    summary_text: str = Field(..., min_length=1)


class ComparisonReportResponse(BaseModel):
    """Структурированный отчёт по сценарию (freemium-превью или полный платный отчёт)."""

    scenario_id: str = Field(..., min_length=1)
    is_unlocked: bool = Field(..., description="Оплачен ли полный отчёт пользователем")
    competitors_count: int = Field(..., ge=0, description="Всего найдено конкурентов")
    locked_competitors_count: int = Field(
        ..., ge=0, description="Сколько конкурентов скрыто до оплаты"
    )
    own_result: Optional[ComparisonResult] = Field(
        default=None, description="Результат проверки предложения своей компании"
    )
    market_summary: Optional[MarketSummary] = Field(
        default=None, description="Сводка по общему рынку (доступна после оплаты)"
    )
    own_positioning: Optional[OwnPositioning] = Field(
        default=None, description="Позиционирование компании на рынке (после оплаты)"
    )
    results: List[ComparisonResult] = Field(
        default_factory=list,
        description="Список результатов (полный или с серверным скрытием до оплаты)",
    )


class ScenarioDetailsDraft(BaseModel):
    """Черновик деталей сценария, извлечённый из произвольного текста на подтверждение."""

    required_works: List[str] = Field(
        default_factory=list,
        description="Атомарные обязательные работы, извлечённые из описания",
    )
    required_components: List[str] = Field(
        default_factory=list,
        description="Требуемые материалы, расходники или комплектующие",
    )
    conditions: List[str] = Field(
        default_factory=list,
        description="Особые условия заказа (срочность, выезд, график и т.д.)",
    )
    needs_confirmation: bool = Field(
        default=True,
        description="Нужно ли подтверждение тегов пользователем перед расчётом",
    )
