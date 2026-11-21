from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class PricingUnit(str, Enum):
    """Единица расчёта цены и объёма услуги."""

    FIXED = "fixed"
    PER_HOUR = "per_hour"
    PER_UNIT = "per_unit"
    PER_SQM = "per_sqm"


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


class Surcharge(BaseModel):
    """Доплата или надбавка к базовой цене услуги."""

    name: str = Field(..., min_length=1, description="Название доплаты")
    amount: Decimal = Field(..., ge=0, description="Размер доплаты")
    unit: PricingUnit = Field(
        default=PricingUnit.FIXED,
        description="Единица расчёта доплаты",
    )
    is_mandatory: bool = Field(
        default=True,
        description="Является ли доплата обязательной для данного условия",
    )
    condition_description: Optional[str] = Field(
        default=None,
        description="Условие, при котором применяется доплата",
    )


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
    pricing_unit: Optional[PricingUnit] = Field(
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
        description="Ограничения и работы, которые точно не входят",
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
    pricing_unit: PricingUnit = Field(
        default=PricingUnit.FIXED,
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


class PriceLineItem(BaseModel):
    """Отдельная строка в детализации расчёта стоимости."""

    label: str = Field(..., min_length=1, description="Пояснение к статье расхода")
    amount: Decimal = Field(..., ge=0, description="Рассчитанная сумма")


class ComparisonResult(BaseModel):
    """Объяснимый результат сопоставления предложения со сценарием."""

    offer_id: str = Field(..., min_length=1, description="ID оцениваемого предложения")
    provider_name: str = Field(..., min_length=1, description="Название исполнителя")
    status: ComparabilityStatus = Field(..., description="Статус сопоставимости")
    completeness: DataCompleteness = Field(..., description="Полнота исходных сведений")
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
