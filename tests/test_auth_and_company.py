from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import EmailDeliveryError
from app.main import app, get_email_sender


class _FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_login_code(self, to_email: str, code: str) -> None:
        self.sent.append((to_email, code))


def test_otp_auth_flow_and_company_profile_in_compare(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    fake_sender = _FakeEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: fake_sender

    try:
        client = TestClient(app)

        # Гость не может получить /me
        assert client.get("/me").status_code == 401

        # Запрос кода
        req_resp = client.post(
            "/auth/request-code",
            json={"email": "  Owner@Example.COM "},
        )
        assert req_resp.status_code == 200
        assert req_resp.json()["email"] == "owner@example.com"
        assert len(fake_sender.sent) == 1
        sent_email, code = fake_sender.sent[0]
        assert sent_email == "owner@example.com"
        assert len(code) == 6

        # Неверный код отклоняется
        bad_resp = client.post(
            "/auth/verify-code",
            json={"email": "owner@example.com", "code": "000000" if code != "000000" else "111111"},
        )
        assert bad_resp.status_code == 400

        # Верный код открывает сессию в HttpOnly cookie
        ok_resp = client.post(
            "/auth/verify-code",
            json={"email": "owner@example.com", "code": code},
        )
        assert ok_resp.status_code == 200
        assert ok_resp.json()["authenticated"] is True

        # Теперь /me доступен, профиля компании ещё нет
        me_resp = client.get("/me")
        assert me_resp.status_code == 200
        assert me_resp.json()["has_company_profile"] is False
        assert client.get("/me/company").status_code == 404

        # Сохраняем предложение своей компании
        own_offer_payload = {
            "id": "ignored-id",
            "provider_name": "Моя компания",
            "service_title": "Настройка под ключ",
            "base_price": "950",
            "pricing_unit": "hour",
            "included_works": ["аудит", "настройка"],
            "included_components": ["материалы"],
        }
        put_resp = client.put("/me/company", json=own_offer_payload)
        assert put_resp.status_code == 200
        assert put_resp.json()["id"].startswith("own-user-")

        assert client.get("/me").json()["has_company_profile"] is True

        # Прямое сравнение автоматически включает предложение своей компании
        compare_resp = client.post(
            "/compare",
            json={
                "scenario": {
                    "id": "sc-1",
                    "title": "Настройка",
                    "required_works": ["аудит", "настройка"],
                    "volume": "10",
                    "pricing_unit": "hour",
                    "required_components": ["материалы"],
                },
                "offers": [
                    {
                        "id": "comp-1",
                        "provider_name": "Конкурент 1",
                        "service_title": "Настройка",
                        "base_price": "1200",
                        "pricing_unit": "hour",
                        "included_works": ["аудит", "настройка"],
                        "included_components": ["материалы"],
                    }
                ],
            },
        )
        assert compare_resp.status_code == 200
        results = compare_resp.json()
        assert len(results) == 2
        assert results[0]["provider_name"] == "Моя компания"
        assert results[0]["is_own_company"] is True
        assert results[0]["total_estimated_price"] == "9500"
        assert results[1]["is_own_company"] is False

        # Выход очищает сессию
        assert client.post("/auth/logout").status_code == 200
        assert client.get("/me").status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_otp_brute_force_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'limit.db'}")
    fake_sender = _FakeEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: fake_sender

    try:
        client = TestClient(app)
        client.post("/auth/request-code", json={"email": "test@example.com"})
        _, code = fake_sender.sent[0]
        wrong_code = "000000" if code != "000000" else "111111"

        for _ in range(4):
            resp = client.post(
                "/auth/verify-code",
                json={"email": "test@example.com", "code": wrong_code},
            )
            assert resp.status_code == 400

        # Пятая неверная попытка блокирует текущий код
        fifth = client.post(
            "/auth/verify-code",
            json={"email": "test@example.com", "code": wrong_code},
        )
        assert fifth.status_code == 429

        # После блокировки даже верный старый код больше не подходит
        after = client.post(
            "/auth/verify-code",
            json={"email": "test@example.com", "code": code},
        )
        assert after.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_smtp_delivery_error_returns_502(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'smtp_err.db'}")

    class _BrokenSender:
        def send_login_code(self, to_email: str, code: str) -> None:
            raise EmailDeliveryError("SMTP timeout")

    app.dependency_overrides[get_email_sender] = lambda: _BrokenSender()
    try:
        client = TestClient(app)
        resp = client.post("/auth/request-code", json={"email": "a@example.com"})
        assert resp.status_code == 502
    finally:
        app.dependency_overrides.clear()


def test_dev_topup_flag_and_user_history(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'history.db'}")
    fake_sender = _FakeEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: fake_sender

    try:
        client = TestClient(app)
        assert client.get("/me/history").status_code == 401

        client.post("/auth/request-code", json={"email": "hist@example.com"})
        _, code = fake_sender.sent[0]
        assert (
            client.post(
                "/auth/verify-code",
                json={"email": "hist@example.com", "code": code},
            ).status_code
            == 200
        )

        monkeypatch.setenv("APP_ENV", "development")
        me_dev = client.get("/me")
        assert me_dev.status_code == 200
        assert me_dev.json()["dev_topup_enabled"] is True

        monkeypatch.setenv("APP_ENV", "production")
        me_prod = client.get("/me")
        assert me_prod.status_code == 200
        assert me_prod.json()["dev_topup_enabled"] is False

        for i in range(6):
            resp = client.post(
                "/scenarios",
                json={"id": f"scen-h-{i}", "title": f"Услуга {i}", "city": "Москва"},
            )
            assert resp.status_code == 200

        hist = client.get("/me/history")
        assert hist.status_code == 200
        items = hist.json()["items"]
        assert len(items) == 5
        assert items[0]["id"] == "scen-h-5"
        assert items[0]["is_unlocked"] is False
    finally:
        app.dependency_overrides.clear()
