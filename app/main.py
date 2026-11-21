from typing import List

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from app.calculator import compare_offers
from app.models import ComparisonResult, OrderScenario, ServiceOffer
from app.storage import SQLiteRepository, resolve_db_path

app = FastAPI(
    title="Сервис интеллектуального сопоставления услуг",
    version="0.1.0",
)


class CompareRequest(BaseModel):
    """Запрос на прямое сравнение предложений под сценарий без сохранения."""

    scenario: OrderScenario
    offers: List[ServiceOffer]


def get_repository() -> SQLiteRepository:
    """Возвращает экземпляр хранилища на основе DATABASE_URL."""
    return SQLiteRepository(resolve_db_path())


@app.get("/health")
def health_check() -> dict[str, str]:
    """Проверка работоспособности API."""
    return {"status": "ok"}


@app.post("/offers", response_model=ServiceOffer)
def create_offer(
    offer: ServiceOffer,
    repo: SQLiteRepository = Depends(get_repository),
) -> ServiceOffer:
    """Сохраняет или обновляет предложение услуги."""
    return repo.save_offer(offer)


@app.get("/offers", response_model=List[ServiceOffer])
def list_offers(
    repo: SQLiteRepository = Depends(get_repository),
) -> List[ServiceOffer]:
    """Возвращает все сохранённые предложения."""
    return repo.list_offers()


@app.post("/scenarios", response_model=OrderScenario)
def create_scenario(
    scenario: OrderScenario,
    repo: SQLiteRepository = Depends(get_repository),
) -> OrderScenario:
    """Сохраняет или обновляет сценарий заказа."""
    return repo.save_scenario(scenario)


@app.get("/scenarios", response_model=List[OrderScenario])
def list_scenarios(
    repo: SQLiteRepository = Depends(get_repository),
) -> List[OrderScenario]:
    """Возвращает все сохранённые сценарии."""
    return repo.list_scenarios()


@app.post("/compare", response_model=List[ComparisonResult])
def compare_direct(payload: CompareRequest) -> List[ComparisonResult]:
    """Сравнивает переданные предложения с переданным сценарием."""
    return compare_offers(payload.offers, payload.scenario)


@app.get("/scenarios/{scenario_id}/compare", response_model=List[ComparisonResult])
def compare_saved_scenario(
    scenario_id: str,
    repo: SQLiteRepository = Depends(get_repository),
) -> List[ComparisonResult]:
    """Сравнивает сохранённый сценарий со всеми сохранёнными предложениями."""
    scenario = repo.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Сценарий не найден")
    offers = repo.list_offers()
    return compare_offers(offers, scenario)
