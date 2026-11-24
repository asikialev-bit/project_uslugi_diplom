import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from app.auth.email_sender import EmailSender
from app.storage import SQLiteRepository

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_OTP_TTL_MINUTES = 10
_OTP_MAX_ATTEMPTS = 5
_SESSION_TTL_DAYS = 7


class AuthError(Exception):
    """Ошибка проверки кода или авторизации пользователя."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def normalize_email(raw_email: str) -> str:
    """Проверяет формат email и приводит его к нижнему регистру."""
    cleaned = raw_email.strip().lower()
    if not cleaned or not _EMAIL_RE.match(cleaned):
        raise AuthError("Укажите корректный адрес электронной почты", status_code=422)
    return cleaned


def _get_auth_secret() -> bytes:
    secret = os.getenv("AUTH_SECRET", "local-dev-secret-change-in-prod")
    return secret.encode("utf-8")


def hash_secret_value(raw_value: str) -> str:
    """Хэширует одноразовый код или токен сессии через HMAC-SHA256."""
    return hmac.new(
        _get_auth_secret(),
        raw_value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_otp_code() -> str:
    """Генерирует криптографически случайный 6-значный код."""
    return f"{secrets.randbelow(1_000_000):06d}"


def generate_session_token() -> str:
    """Генерирует случайный токен пользовательской сессии."""
    return secrets.token_urlsafe(32)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    """Сервис беспарольной авторизации по одноразовым кодам на email."""

    def __init__(
        self,
        repo: SQLiteRepository,
        email_sender: EmailSender,
    ) -> None:
        self.repo = repo
        self.email_sender = email_sender

    def request_code(self, raw_email: str) -> str:
        email = normalize_email(raw_email)
        code = generate_otp_code()
        expires_at = (_utc_now() + timedelta(minutes=_OTP_TTL_MINUTES)).isoformat()
        self.repo.save_auth_code(
            email=email,
            code_hash=hash_secret_value(code),
            expires_at=expires_at,
        )
        self.email_sender.send_login_code(email, code)
        return email

    def verify_code(self, raw_email: str, raw_code: str) -> Tuple[Dict[str, str], str]:
        email = normalize_email(raw_email)
        code = raw_code.strip()
        if not code:
            raise AuthError("Введите код подтверждения", status_code=422)

        record = self.repo.get_auth_code(email)
        if record is None:
            raise AuthError("Сначала запросите код на почту", status_code=400)

        now = _utc_now()
        expires_at = datetime.fromisoformat(record["expires_at"])
        if now > expires_at:
            self.repo.delete_auth_code(email)
            raise AuthError("Срок действия кода истёк, запросите новый", status_code=400)

        if record["attempts"] >= _OTP_MAX_ATTEMPTS:
            self.repo.delete_auth_code(email)
            raise AuthError(
                "Превышено число попыток, запросите новый код",
                status_code=429,
            )

        expected_hash = record["code_hash"]
        actual_hash = hash_secret_value(code)
        if not hmac.compare_digest(actual_hash, expected_hash):
            attempts = self.repo.increment_auth_code_attempts(email)
            if attempts >= _OTP_MAX_ATTEMPTS:
                self.repo.delete_auth_code(email)
                raise AuthError(
                    "Превышено число попыток, запросите новый код",
                    status_code=429,
                )
            raise AuthError("Неверный код подтверждения", status_code=400)

        self.repo.delete_auth_code(email)
        user = self.repo.get_or_create_user(email)
        raw_token = generate_session_token()
        session_expires = (_utc_now() + timedelta(days=_SESSION_TTL_DAYS)).isoformat()
        self.repo.create_session(
            token_hash=hash_secret_value(raw_token),
            user_id=user["id"],
            expires_at=session_expires,
        )
        return user, raw_token

    def get_current_user(self, raw_token: Optional[str]) -> Optional[Dict[str, str]]:
        if not raw_token:
            return None
        return self.repo.get_user_by_session_token_hash(
            token_hash=hash_secret_value(raw_token),
            now_iso=_utc_now().isoformat(),
        )

    def logout(self, raw_token: Optional[str]) -> None:
        if not raw_token:
            return
        self.repo.delete_session(hash_secret_value(raw_token))
