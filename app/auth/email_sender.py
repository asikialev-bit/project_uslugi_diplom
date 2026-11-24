import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Ошибка отправки письма с одноразовым кодом."""


class EmailSender(Protocol):
    """Абстрактный интерфейс отправки одноразового кода на почту."""

    def send_login_code(self, to_email: str, code: str) -> None:
        """Отправляет 6-значный код подтверждения на указанный email."""
        ...


class ConsoleEmailSender:
    """Dev-отправщик для локальной разработки: выводит код в лог."""

    def __init__(self) -> None:
        self.last_sent: Optional[tuple[str, str]] = None

    def send_login_code(self, to_email: str, code: str) -> None:
        self.last_sent = (to_email, code)
        logger.info("OTP login code for %s: %s", to_email, code)
        print(f"[DEV OTP] Email: {to_email} | Код входа: {code}")


class SMTPEmailSender:
    """Отправка одноразовых кодов через внешний SMTP-сервер."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: Optional[str] = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.host = host.strip()
        self.port = port
        self.username = username.strip()
        self.password = password
        self.from_email = (from_email or username).strip()
        self.timeout_seconds = timeout_seconds

    def send_login_code(self, to_email: str, code: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"Код входа в СметАнализ: {code}"
        msg["From"] = self.from_email
        msg["To"] = to_email
        msg.set_content(
            f"Ваш одноразовый код для входа в СметАнализ: {code}\n\n"
            "Код действует 10 минут. Если вы не запрашивали вход, просто проигнорируйте письмо."
        )

        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(
                    self.host, self.port, timeout=self.timeout_seconds
                ) as server:
                    server.login(self.username, self.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(
                    self.host, self.port, timeout=self.timeout_seconds
                ) as server:
                    server.starttls()
                    server.login(self.username, self.password)
                    server.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailDeliveryError(
                f"Не удалось отправить письмо на {to_email}: {exc}"
            ) from exc


def get_email_sender_from_env() -> EmailSender:
    """Выбирает SMTP при наличии настроек в окружении, иначе ConsoleEmailSender."""
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    port_raw = os.getenv("SMTP_PORT", "465").strip() or "465"
    from_email = os.getenv("SMTP_FROM", "").strip() or None

    if host and user and password:
        return SMTPEmailSender(
            host=host,
            port=int(port_raw),
            username=user,
            password=password,
            from_email=from_email,
        )
    return ConsoleEmailSender()
