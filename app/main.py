import os
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.auth import (
    AuthError,
    AuthService,
    EmailDeliveryError,
    EmailSender,
    get_email_sender_from_env,
)
from app.calculator import build_comparison_report, compare_offers
from app.discovery import DiscoveryService, SearchProviderError
from app.llm import (
    LLMConfigurationError,
    LLMProviderError,
    OfferExtractionError,
    OfferExtractor,
    OpenAICompatibleLLMClient,
    ScenarioDetailsExtractor,
    ScenarioExtractionError,
    UnitConversionEstimator,
)
from app.models import (
    ComparabilityStatus,
    ComparisonReportResponse,
    ComparisonResult,
    DataCompleteness,
    OrderScenario,
    ProviderType,
    ScenarioDetailsDraft,
    ServiceOffer,
)
from app.storage import InsufficientCreditsError, SQLiteRepository, resolve_db_path

load_dotenv()

SESSION_COOKIE_NAME = "servicematch_session"

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
    include_own_company: bool = Field(
        default=True,
        description="Автоматически добавлять профиль своей компании, если пользователь вошёл",
    )


class ExtractOfferRequest(BaseModel):
    """Запрос на извлечение структурированного предложения из сырого текста."""

    raw_text: str = Field(..., min_length=1, description="Текст предложения конкурента")
    offer_id: Optional[str] = Field(default=None, description="Необязательный ID")
    provider_name: Optional[str] = Field(
        default=None,
        description="Имя исполнителя, если оно не указано в самом тексте",
    )


class ExtractScenarioDetailsRequest(BaseModel):
    """Запрос на разбор произвольного описания сценария в теги на подтверждение."""

    raw_text: str = Field(..., min_length=1, description="Произвольное описание заказа")
    service_title: Optional[str] = Field(
        default=None, description="Базовое название услуги для контекста"
    )


class RequestCodePayload(BaseModel):
    """Запрос на отправку одноразового кода входа на email."""

    email: str = Field(..., min_length=3)


class VerifyCodePayload(BaseModel):
    """Запрос на проверку одноразового кода входа."""

    email: str = Field(..., min_length=3)
    code: str = Field(..., min_length=1)


class TopupCreditsPayload(BaseModel):
    """Запрос на тестовое начисление кредитов в режиме разработки."""

    amount: int = Field(..., gt=0, le=1000)


def get_repository() -> SQLiteRepository:
    """Возвращает экземпляр хранилища на основе DATABASE_URL."""
    return SQLiteRepository(resolve_db_path())


def get_email_sender() -> EmailSender:
    """Возвращает отправщик писем (SMTP из .env или консольный в dev)."""
    return get_email_sender_from_env()


def get_auth_service(
    repo: SQLiteRepository = Depends(get_repository),
    email_sender: EmailSender = Depends(get_email_sender),
) -> AuthService:
    """Создаёт сервис авторизации."""
    return AuthService(repo=repo, email_sender=email_sender)


def _extract_session_token(request: Request) -> Optional[str]:
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip() or None
    return None


def get_optional_user(
    request: Request,
    repo: SQLiteRepository = Depends(get_repository),
    email_sender: EmailSender = Depends(get_email_sender),
) -> Optional[Dict[str, str]]:
    """Возвращает текущего пользователя по сессии или None для гостя."""
    token = _extract_session_token(request)
    if not token:
        return None
    service = AuthService(repo=repo, email_sender=email_sender)
    return service.get_current_user(token)


def require_user(
    user: Optional[Dict[str, str]] = Depends(get_optional_user),
) -> Dict[str, str]:
    """Требует авторизованного пользователя."""
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    return user


def get_offer_extractor() -> OfferExtractor:
    """Создаёт экстрактор предложений на основе переменных окружения."""
    client = OpenAICompatibleLLMClient.from_env()
    return OfferExtractor(client)


def get_scenario_extractor() -> ScenarioDetailsExtractor:
    """Создаёт экстрактор деталей сценария на основе переменных окружения."""
    client = OpenAICompatibleLLMClient.from_env()
    return ScenarioDetailsExtractor(client)


def get_discovery_service() -> DiscoveryService:
    """Создаёт сервис поиска конкурентов (работает и без LLM для лёгкого discovery)."""
    extractor: Optional[OfferExtractor] = None
    try:
        extractor = get_offer_extractor()
    except LLMConfigurationError:
        extractor = None
    return DiscoveryService.from_env(extractor=extractor)


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


@app.post("/auth/request-code")
def request_auth_code(
    payload: RequestCodePayload,
    auth: AuthService = Depends(get_auth_service),
) -> Dict[str, object]:
    """Отправляет одноразовый код входа на email."""
    email = auth.request_code(payload.email)
    return {"sent": True, "email": email}


@app.post("/auth/verify-code")
def verify_auth_code(
    payload: VerifyCodePayload,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> Dict[str, object]:
    """Проверяет одноразовый код и открывает сессию в HttpOnly cookie."""
    user, raw_token = auth.verify_code(payload.email, payload.code)
    is_prod = os.getenv("APP_ENV", "development").lower() == "production"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        max_age=7 * 24 * 60 * 60,
    )
    return {"authenticated": True, "user": user}


@app.post("/auth/logout")
def logout_user(
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> Dict[str, bool]:
    """Завершает текущую сессию пользователя."""
    token = _extract_session_token(request)
    auth.logout(token)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@app.get("/me")
def read_current_user(
    user: Dict[str, str] = Depends(require_user),
    repo: SQLiteRepository = Depends(get_repository),
) -> Dict[str, object]:
    """Возвращает данные текущего пользователя, профиль компании и баланс кредитов."""
    company_offer = repo.get_company_offer(user["id"])
    return {
        "user": user,
        "has_company_profile": company_offer is not None,
        "credits_balance": repo.get_credit_balance(user["id"]),
        "dev_topup_enabled": os.getenv("APP_ENV", "development").lower() != "production",
    }


@app.get("/me/history")
def read_user_history(
    user: Dict[str, str] = Depends(require_user),
    repo: SQLiteRepository = Depends(get_repository),
) -> Dict[str, object]:
    """Возвращает последние 5 проверок (сценариев) текущего пользователя."""
    return {"items": repo.list_recent_scenarios_for_user(user["id"], limit=5)}


@app.get("/credits")
def read_credits_wallet(
    user: Dict[str, str] = Depends(require_user),
    repo: SQLiteRepository = Depends(get_repository),
) -> Dict[str, object]:
    """Возвращает текущий баланс кредитов и историю операций."""
    return {
        "balance": repo.get_credit_balance(user["id"]),
        "transactions": repo.list_credit_transactions(user["id"]),
    }


@app.post("/credits/topup")
def topup_credits_dev(
    payload: TopupCreditsPayload,
    user: Dict[str, str] = Depends(require_user),
    repo: SQLiteRepository = Depends(get_repository),
) -> Dict[str, object]:
    """Временное начисление кредитов для локального тестирования (отключено в production)."""
    if os.getenv("APP_ENV", "development").lower() == "production":
        raise HTTPException(
            status_code=403,
            detail="Тестовое пополнение кредитов отключено в production",
        )
    new_balance = repo.add_credits(
        user_id=user["id"],
        amount=payload.amount,
        reason="dev_topup",
    )
    return {"balance": new_balance, "added": payload.amount}


@app.get("/me/company", response_model=ServiceOffer)
def read_company_profile(
    user: Dict[str, str] = Depends(require_user),
    repo: SQLiteRepository = Depends(get_repository),
) -> ServiceOffer:
    """Возвращает сохранённое предложение своей компании."""
    offer = repo.get_company_offer(user["id"])
    if offer is None:
        raise HTTPException(status_code=404, detail="Профиль компании ещё не заполнен")
    return offer


@app.put("/me/company", response_model=ServiceOffer)
def save_company_profile(
    offer: ServiceOffer,
    user: Dict[str, str] = Depends(require_user),
    repo: SQLiteRepository = Depends(get_repository),
) -> ServiceOffer:
    """Сохраняет предложение своей компании для участия в сравнениях."""
    own_offer = offer.model_copy(update={"id": f"own-{user['id']}"})
    return repo.save_company_offer(user["id"], own_offer)


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


@app.delete("/offers/{offer_id}")
def delete_offer(
    offer_id: str,
    repo: SQLiteRepository = Depends(get_repository),
) -> Dict[str, object]:
    """Удаляет сохранённое предложение по ID."""
    if not repo.delete_offer(offer_id):
        raise HTTPException(status_code=404, detail="Предложение не найдено")
    return {"deleted": True, "id": offer_id}


@app.post("/offers/extract", response_model=ServiceOffer)
def extract_offer_from_text(
    payload: ExtractOfferRequest,
    user: Dict[str, str] = Depends(require_user),
    extractor: OfferExtractor = Depends(get_offer_extractor),
) -> ServiceOffer:
    """Извлекает структурированное предложение из текста через LLM (только для авторизованных)."""
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
    user: Optional[Dict[str, str]] = Depends(get_optional_user),
    repo: SQLiteRepository = Depends(get_repository),
) -> OrderScenario:
    """Сохраняет или обновляет сценарий заказа."""
    return repo.save_scenario(scenario, user_id=user["id"] if user else None)


@app.post("/scenarios/extract-details", response_model=ScenarioDetailsDraft)
def extract_scenario_details(
    payload: ExtractScenarioDetailsRequest,
    user: Dict[str, str] = Depends(require_user),
    extractor: ScenarioDetailsExtractor = Depends(get_scenario_extractor),
) -> ScenarioDetailsDraft:
    """Разбирает произвольное описание заказа в теги для подтверждения пользователем."""
    try:
        return extractor.extract(
            raw_text=payload.raw_text,
            service_title=payload.service_title,
        )
    except ScenarioExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/scenarios", response_model=List[OrderScenario])
def list_scenarios(
    repo: SQLiteRepository = Depends(get_repository),
) -> List[OrderScenario]:
    """Возвращает все сохранённые сценарии."""
    return repo.list_scenarios()


@app.delete("/scenarios/{scenario_id}")
def delete_scenario(
    scenario_id: str,
    repo: SQLiteRepository = Depends(get_repository),
) -> Dict[str, object]:
    """Удаляет сохранённый сценарий по ID."""
    if not repo.delete_scenario(scenario_id):
        raise HTTPException(status_code=404, detail="Сценарий не найден")
    return {"deleted": True, "id": scenario_id}


def _merge_own_company(
    offers: List[ServiceOffer],
    user: Optional[Dict[str, str]],
    repo: SQLiteRepository,
    include_own_company: bool = True,
) -> tuple[List[ServiceOffer], Optional[str]]:
    if not include_own_company or user is None:
        return offers, None
    company_offer = repo.get_company_offer(user["id"])
    if company_offer is None:
        return offers, None
    merged = list(offers)
    if not any(o.id == company_offer.id for o in merged):
        merged.append(company_offer)
    return merged, company_offer.id


@app.post("/compare", response_model=List[ComparisonResult])
def compare_direct(
    payload: CompareRequest,
    user: Optional[Dict[str, str]] = Depends(get_optional_user),
    repo: SQLiteRepository = Depends(get_repository),
) -> List[ComparisonResult]:
    """Сравнивает переданные предложения с переданным сценарием."""
    offers, own_id = _merge_own_company(
        payload.offers, user, repo, include_own_company=payload.include_own_company
    )
    return compare_offers(offers, payload.scenario, own_offer_id=own_id)


@app.get("/scenarios/{scenario_id}/compare", response_model=List[ComparisonResult])
def compare_saved_scenario(
    scenario_id: str,
    user: Optional[Dict[str, str]] = Depends(get_optional_user),
    repo: SQLiteRepository = Depends(get_repository),
) -> List[ComparisonResult]:
    """Сравнивает сохранённый сценарий со всеми сохранёнными предложениями."""
    scenario = repo.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Сценарий не найден")
    offers, own_id = _merge_own_company(repo.list_offers(), user, repo)
    return compare_offers(offers, scenario, own_offer_id=own_id)


def _append_discovery_placeholders(
    report: ComparisonReportResponse,
    scenario: OrderScenario,
    existing_offers: List[ServiceOffer],
    discovery: DiscoveryService,
    repo: SQLiteRepository,
) -> ComparisonReportResponse:
    """Добавляет заблокированные слоты по результатам лёгкого discovery без LLM."""
    if not discovery.is_live_configured:
        return report
    try:
        candidates = discovery.discover_candidates(scenario, limit=15, repo=repo)
    except SearchProviderError:
        return report
    known_urls = {o.source_url for o in existing_offers if o.source_url}
    new_candidates = [c for c in candidates if not c.url or c.url not in known_urls]
    if not new_candidates:
        return report

    extra_results = list(report.results)
    start_idx = report.locked_competitors_count + 1
    show_first_preview = report.competitors_count == 0
    locked_added = 0
    for offset, cand in enumerate(new_candidates):
        if show_first_preview and offset == 0:
            extra_results.append(
                ComparisonResult(
                    offer_id="preview-disc-1",
                    provider_name=cand.title[:80],
                    is_own_company=False,
                    is_locked=False,
                    provider_type=cand.provider_type,
                    status=ComparabilityStatus.PARTIALLY_COMPARABLE,
                    completeness=DataCompleteness.PARTIAL,
                    similarity_score=0,
                    differences=[
                        cand.snippet[:260]
                        if cand.snippet
                        else "Найден в поиске; полный разбор цены и доплат откроется после оплаты."
                    ],
                    missing_info=["Детальная смета и состав работ загружаются при разблокировке отчёта"],
                )
            )
            continue

        slot_num = start_idx + locked_added
        locked_added += 1
        extra_results.append(
            ComparisonResult(
                offer_id=f"locked-disc-{slot_num}",
                provider_name=f"Найденный конкурент #{slot_num}",
                is_own_company=False,
                is_locked=True,
                provider_type=ProviderType.UNKNOWN,
                status=ComparabilityStatus.PARTIALLY_COMPARABLE,
                completeness=DataCompleteness.INSUFFICIENT,
                similarity_score=0,
            )
        )
    return report.model_copy(
        update={
            "competitors_count": report.competitors_count + len(new_candidates),
            "locked_competitors_count": report.locked_competitors_count + locked_added,
            "results": extra_results,
        }
    )


def _get_offers_for_report(
    repo: SQLiteRepository,
    scenario_id: str,
    discovery: DiscoveryService,
) -> List[ServiceOffer]:
    scoped = repo.list_offers_for_scenario(scenario_id)
    if discovery.is_live_configured:
        return scoped
    return scoped or repo.list_offers()


@app.get("/scenarios/{scenario_id}/report", response_model=ComparisonReportResponse)
def get_scenario_report(
    scenario_id: str,
    user: Optional[Dict[str, str]] = Depends(get_optional_user),
    repo: SQLiteRepository = Depends(get_repository),
    discovery: DiscoveryService = Depends(get_discovery_service),
) -> ComparisonReportResponse:
    """Возвращает freemium-превью или оплаченный полный отчёт по сценарию."""
    scenario = repo.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Сценарий не найден")
    stored_offers = _get_offers_for_report(repo, scenario_id, discovery)
    offers, own_id = _merge_own_company(stored_offers, user, repo)
    is_unlocked = bool(user and repo.is_scenario_unlocked(user["id"], scenario_id))
    report = build_comparison_report(
        offers,
        scenario,
        own_offer_id=own_id,
        is_unlocked=is_unlocked,
    )
    if not is_unlocked:
        report = _append_discovery_placeholders(
            report, scenario, stored_offers, discovery, repo
        )
    return report


@app.post("/scenarios/{scenario_id}/unlock", response_model=ComparisonReportResponse)
def unlock_scenario_report(
    scenario_id: str,
    user: Dict[str, str] = Depends(require_user),
    repo: SQLiteRepository = Depends(get_repository),
    discovery: DiscoveryService = Depends(get_discovery_service),
) -> ComparisonReportResponse:
    """Списывает 1 кредит (идемпотентно), при необходимости собирает конкурентов и открывает отчёт."""
    scenario = repo.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Сценарий не найден")
    charged, _ = repo.unlock_scenario_with_credit(user["id"], scenario_id, cost=1)
    if charged and discovery.is_live_configured:
        discovery.collect_offers_for_scenario(scenario, repo=repo)
    stored_offers = _get_offers_for_report(repo, scenario_id, discovery)
    offers, own_id = _merge_own_company(stored_offers, user, repo)
    target_units = [o.pricing_unit for o in offers if o.pricing_unit]
    llm_client = discovery.extractor.client if discovery.extractor is not None else None
    estimated_conversions = UnitConversionEstimator(llm_client).estimate_conversions(
        scenario, target_units
    )
    if estimated_conversions:
        merged_conversions = {**estimated_conversions, **scenario.unit_conversions}
        scenario = scenario.model_copy(update={"unit_conversions": merged_conversions})
        repo.save_scenario(scenario)
    return build_comparison_report(
        offers,
        scenario,
        own_offer_id=own_id,
        is_unlocked=True,
    )


@app.exception_handler(LLMConfigurationError)
def handle_llm_config_error(_, exc: LLMConfigurationError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(LLMProviderError)
def handle_llm_provider_error(_, exc: LLMProviderError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(AuthError)
def handle_auth_error(_, exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(InsufficientCreditsError)
def handle_insufficient_credits(_, exc: InsufficientCreditsError) -> JSONResponse:
    return JSONResponse(status_code=402, content={"detail": str(exc)})


@app.exception_handler(SearchProviderError)
def handle_search_provider_error(_, exc: SearchProviderError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(EmailDeliveryError)
def handle_email_delivery_error(_, exc: EmailDeliveryError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})
