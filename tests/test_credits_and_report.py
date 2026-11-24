from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_email_sender
from app.storage import InsufficientCreditsError, SQLiteRepository


class _CaptureEmailSender:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {}

    def send_login_code(self, to_email: str, code: str) -> None:
        self.codes[to_email] = code


def _login(client: TestClient, sender: _CaptureEmailSender, email: str) -> None:
    resp_req = client.post("/auth/request-code", json={"email": email})
    assert resp_req.status_code == 200
    code = sender.codes[email.strip().lower()]
    resp_ver = client.post(
        "/auth/verify-code", json={"email": email, "code": code}
    )
    assert resp_ver.status_code == 200


def test_credit_ledger_atomic_deduction_and_idempotency(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "credits.db"))
    user = repo.get_or_create_user("client@example.com")
    user_id = user["id"]

    # Новый пользователь стартует строго с 0 кредитов
    assert repo.get_credit_balance(user_id) == 0

    with pytest.raises(InsufficientCreditsError):
        repo.unlock_scenario_with_credit(user_id, "scen-1", cost=1)
    assert repo.get_credit_balance(user_id) == 0
    assert repo.is_scenario_unlocked(user_id, "scen-1") is False

    new_balance = repo.add_credits(user_id, 2, reason="dev_topup")
    assert new_balance == 2

    charged, remaining = repo.unlock_scenario_with_credit(user_id, "scen-1", cost=1)
    assert charged is True
    assert remaining == 1
    assert repo.is_scenario_unlocked(user_id, "scen-1") is True

    # Повторное открытие того же сценария не списывает второй кредит
    charged_again, remaining_again = repo.unlock_scenario_with_credit(
        user_id, "scen-1", cost=1
    )
    assert charged_again is False
    assert remaining_again == 1

    txs = repo.list_credit_transactions(user_id)
    assert len(txs) == 2
    assert txs[0]["delta"] == -1
    assert txs[0]["reference_id"] == "scen-1"
    assert txs[1]["delta"] == 2


def test_freemium_report_masks_market_and_unlock_reveals_full_analysis(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'report.db'}")
    sender = _CaptureEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender

    try:
        client = TestClient(app)

        # Заполняем 3 конкурента и 1 сценарий
        competitors = [
            {
                "id": "comp-1",
                "provider_name": "Конкурент Эконом",
                "provider_type": "private",
                "service_title": "Уборка квартиры",
                "base_price": "100",
                "pricing_unit": "sqm",
                "included_works": ["мытьё полов", "санузел"],
                "city": "Екатеринбург",
            },
            {
                "id": "comp-2",
                "provider_name": "Конкурент Стандарт",
                "provider_type": "company",
                "service_title": "Уборка квартиры",
                "base_price": "150",
                "pricing_unit": "sqm",
                "included_works": ["мытьё полов", "санузел"],
                "city": "Екатеринбург",
            },
            {
                "id": "comp-3",
                "provider_name": "Конкурент Премиум",
                "provider_type": "company",
                "service_title": "Уборка квартиры",
                "base_price": "220",
                "pricing_unit": "sqm",
                "included_works": ["мытьё полов", "санузел"],
                "city": "Екатеринбург",
            },
        ]
        for offer in competitors:
            assert client.post("/offers", json=offer).status_code == 200

        scenario_payload = {
            "id": "scen-clean",
            "title": "Уборка квартиры",
            "required_works": ["мытьё полов", "санузел"],
            "volume": "50",
            "pricing_unit": "sqm",
            "city": "Екатеринбург",
        }
        assert client.post("/scenarios", json=scenario_payload).status_code == 200

        # Авторизуемся и задаём профиль своей компании
        _login(client, sender, "owner@example.com")
        me_resp = client.get("/me")
        assert me_resp.status_code == 200
        assert me_resp.json()["credits_balance"] == 0

        assert (
            client.put(
                "/me/company",
                json={
                    "id": "ignored",
                    "provider_name": "Моя Компания",
                    "provider_type": "company",
                    "service_title": "Уборка квартиры",
                    "base_price": "120",
                    "pricing_unit": "sqm",
                    "included_works": ["мытьё полов", "санузел"],
                    "city": "Екатеринбург",
                },
            ).status_code
            == 200
        )

        # 1. Бесплатное превью отчёта до оплаты
        free_resp = client.get("/scenarios/scen-clean/report")
        assert free_resp.status_code == 200
        free_data = free_resp.json()

        assert free_data["is_unlocked"] is False
        assert free_data["competitors_count"] == 3
        assert free_data["locked_competitors_count"] == 2
        assert free_data["market_summary"] is None
        assert free_data["own_positioning"] is None
        assert free_data["own_result"] is not None
        assert free_data["own_result"]["is_own_company"] is True
        assert free_data["own_result"]["is_locked"] is False
        assert free_data["own_result"]["total_estimated_price"] == "6000"

        locked_items = [r for r in free_data["results"] if r["is_locked"]]
        unlocked_competitors = [
            r
            for r in free_data["results"]
            if not r["is_locked"] and not r["is_own_company"]
        ]
        assert len(unlocked_competitors) == 1
        assert len(locked_items) == 2
        for item in locked_items:
            assert item["offer_id"].startswith("locked-")
            assert item["provider_name"].startswith("Скрытый конкурент #")
            assert item["provider_type"] == "unknown"
            assert item["total_estimated_price"] is None
            assert item["price_breakdown"] == []
            assert item["differences"] == []
            assert item["missing_info"] == []
            assert item["similarity_breakdown"] is None

        # 2. Попытка открыть отчёт при балансе 0 возвращает 402
        no_money_resp = client.post("/scenarios/scen-clean/unlock")
        assert no_money_resp.status_code == 402

        # 3. В production-режиме dev-пополнение запрещено
        monkeypatch.setenv("APP_ENV", "production")
        assert client.post("/credits/topup", json={"amount": 2}).status_code == 403
        monkeypatch.setenv("APP_ENV", "development")

        # 4. Пополняем 2 кредита и разблокируем отчёт
        topup_resp = client.post("/credits/topup", json={"amount": 2})
        assert topup_resp.status_code == 200
        assert topup_resp.json()["balance"] == 2

        unlock_resp = client.post("/scenarios/scen-clean/unlock")
        assert unlock_resp.status_code == 200
        paid_data = unlock_resp.json()

        assert paid_data["is_unlocked"] is True
        assert paid_data["competitors_count"] == 3
        assert paid_data["locked_competitors_count"] == 0

        # Проверяем сводку рынка (5000, 7500, 11000 -> min=5000, median=7500, max=11000)
        summary = paid_data["market_summary"]
        assert summary is not None
        assert summary["total_offers_found"] == 3
        assert summary["comparable_offers_count"] == 3
        assert summary["min_price"] == "5000"
        assert summary["median_price"] == "7500"
        assert summary["max_price"] == "11000"
        assert summary["segments"]["private"]["total_offers_found"] == 1
        assert summary["segments"]["private"]["median_price"] == "5000"
        assert summary["segments"]["company"]["total_offers_found"] == 2
        assert summary["segments"]["company"]["min_price"] == "7500"
        assert summary["segments"]["company"]["median_price"] == "9250"
        assert summary["segments"]["company"]["max_price"] == "11000"

        # Позиционирование своей компании (6000 vs 5000, 7500, 11000 -> ранг 2 из 4, -20% от медианы)
        # И внутри сегмента компаний (6000 vs 7500, 11000 -> 1-е место из 3 компаний)
        pos = paid_data["own_positioning"]
        assert pos is not None
        assert pos["own_provider_type"] == "company"
        assert pos["own_price"] == "6000"
        assert pos["price_rank"] == 2
        assert pos["ranked_offers_count"] == 4
        assert pos["diff_from_median_amount"] == "-1500"
        assert pos["diff_from_median_percent"] == "-20"
        assert pos["segment_price_rank"] == 1
        assert pos["segment_ranked_count"] == 3
        assert "Среди компаний" in pos["segment_summary_text"]
        assert "ниже медианы" in pos["summary_text"]

        # Все конкуренты открыты и имеют детализацию
        assert all(not r["is_locked"] for r in paid_data["results"])
        assert client.get("/credits").json()["balance"] == 1

        # Повторное обращение к /report отдаёт полный отчёт без доп. списаний
        repeat_report = client.get("/scenarios/scen-clean/report")
        assert repeat_report.status_code == 200
        assert repeat_report.json()["is_unlocked"] is True
        assert client.get("/credits").json()["balance"] == 1
    finally:
        app.dependency_overrides.clear()
