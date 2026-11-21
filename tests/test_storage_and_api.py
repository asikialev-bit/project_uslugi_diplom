from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models import OrderScenario, ServiceOffer
from app.storage import SQLiteRepository

client = TestClient(app)


def test_sqlite_repository_crud(tmp_path: Path) -> None:
    repo = SQLiteRepository(str(tmp_path / "repo.db"))
    offer = ServiceOffer(
        id="offer-1",
        provider_name="Исполнитель А",
        service_title="Услуга",
        base_price="100",
        pricing_unit="sqm",
    )
    scenario = OrderScenario(
        id="scen-1",
        title="Заказ 50 кв.м",
        volume="50",
        pricing_unit="sqm",
    )

    repo.save_offer(offer)
    repo.save_scenario(scenario)

    assert len(repo.list_offers()) == 1
    assert repo.get_offer("offer-1") is not None
    assert len(repo.list_scenarios()) == 1
    assert repo.get_scenario("scen-1") is not None


def test_api_offers_scenarios_and_compare(tmp_path: Path, monkeypatch) -> None:
    db_file = tmp_path / "api.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    offer_payload = {
        "id": "offer-1",
        "provider_name": "Исполнитель А",
        "service_title": "Уборка офиса",
        "base_price": "100",
        "pricing_unit": "per_sqm",
        "included_works": ["мытьё полов"],
        "included_components": ["моющие средства"],
    }
    scenario_payload = {
        "id": "scen-1",
        "title": "Офис 40 кв.м",
        "required_works": ["мытьё полов"],
        "volume": "40",
        "pricing_unit": "per_sqm",
        "required_components": ["моющие средства"],
    }

    r_offer = client.post("/offers", json=offer_payload)
    assert r_offer.status_code == 200
    assert len(client.get("/offers").json()) == 1

    r_scen = client.post("/scenarios", json=scenario_payload)
    assert r_scen.status_code == 200
    assert len(client.get("/scenarios").json()) == 1

    r_saved_compare = client.get("/scenarios/scen-1/compare")
    assert r_saved_compare.status_code == 200
    data = r_saved_compare.json()
    assert len(data) == 1
    assert data[0]["status"] == "comparable"
    assert data[0]["completeness"] == "complete"
    assert data[0]["total_estimated_price"] == "4000"

    r_not_found = client.get("/scenarios/unknown/compare")
    assert r_not_found.status_code == 404


def test_api_direct_compare() -> None:
    payload = {
        "scenario": {
            "id": "s-direct",
            "title": "Тест",
            "required_works": ["покраска"],
            "volume": "10",
            "pricing_unit": "per_sqm",
        },
        "offers": [
            {
                "id": "o-direct",
                "provider_name": "Мастер",
                "service_title": "Покраска",
                "base_price": "250",
                "pricing_unit": "per_sqm",
                "included_works": ["покраска"],
            }
        ],
    }

    resp = client.post("/compare", json=payload)
    assert resp.status_code == 200
    result = resp.json()
    assert result[0]["total_estimated_price"] == "2500"
