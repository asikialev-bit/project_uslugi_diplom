from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.calculator import compare_offers
from app.llm import (
    LLMConfigurationError,
    OfferExtractionError,
    OfferExtractor,
    OpenAICompatibleLLMClient,
)
from app.models import ComparisonResult, OrderScenario, ServiceOffer
from app.storage import SQLiteRepository, resolve_db_path

app = FastAPI(
    title="Сервис интеллектуального сопоставления услуг",
    version="0.1.0",
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


class CompareRequest(BaseModel):
    """Запрос на прямое сравнение предложений под сценарий без сохранения."""

    scenario: OrderScenario
    offers: List[ServiceOffer]


class ExtractOfferRequest(BaseModel):
    """Запрос на извлечение структурированного предложения из сырого текста."""

    raw_text: str = Field(..., min_length=1, description="Текст предложения конкурента")
    offer_id: Optional[str] = Field(default=None, description="Необязательный ID")
    provider_name: Optional[str] = Field(
        default=None,
        description="Имя исполнителя, если оно не указано в самом тексте",
    )


def get_repository() -> SQLiteRepository:
    """Возвращает экземпляр хранилища на основе DATABASE_URL."""
    return SQLiteRepository(resolve_db_path())


def get_offer_extractor() -> OfferExtractor:
    """Создаёт экстрактор предложений на основе переменных окружения."""
    client = OpenAICompatibleLLMClient.from_env()
    return OfferExtractor(client)


@app.get("/", include_in_schema=False)
def read_landing_page() -> FileResponse:
    """Возвращает обзорную страницу сервиса."""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/workspace", include_in_schema=False)
def read_workspace_page() -> FileResponse:
    """Возвращает страницу рабочего инструмента сравнения."""
    return FileResponse(FRONTEND_DIR / "workspace.html")


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


@app.post("/offers/extract", response_model=ServiceOffer)
def extract_offer_from_text(
    payload: ExtractOfferRequest,
    extractor: OfferExtractor = Depends(get_offer_extractor),
) -> ServiceOffer:
    """Извлекает структурированное предложение из текста через LLM."""
    try:
        return extractor.extract(
            raw_text=payload.raw_text,
            offer_id=payload.offer_id,
            provider_name=payload.provider_name,
        )
    except OfferExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


@app.exception_handler(LLMConfigurationError)
def handle_llm_config_error(_, exc: LLMConfigurationError):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=503, content={"detail": str(exc)})
