import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.models import OrderScenario, ServiceOffer


class InsufficientCreditsError(Exception):
    """Ошибка нехватки кредитов на балансе пользователя."""

    def __init__(self, balance: int, required: int) -> None:
        self.balance = balance
        self.required = required
        super().__init__(
            f"Недостаточно кредитов: требуется {required}, доступно {balance}"
        )


def resolve_db_path(database_url: Optional[str] = None) -> str:
    """Преобразует DATABASE_URL вида sqlite:///... в путь к файлу SQLite."""
    raw = database_url or os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
    if raw.startswith("sqlite:///"):
        return raw[len("sqlite:///") :]
    return raw


class SQLiteRepository:
    """Изолированный репозиторий для хранения данных сервиса в SQLite."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS offers (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scenarios (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_codes (
                    email TEXT PRIMARY KEY,
                    code_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS company_profiles (
                    user_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS credit_ledger (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    delta INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    reference_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_unlocks (
                    user_id TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    unlocked_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, scenario_id)
                )
                """
            )

    def save_offer(self, offer: ServiceOffer) -> ServiceOffer:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO offers (id, payload) VALUES (?, ?)",
                (offer.id, offer.model_dump_json()),
            )
        return offer

    def list_offers(self) -> List[ServiceOffer]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM offers ORDER BY rowid").fetchall()
        return [ServiceOffer.model_validate_json(row[0]) for row in rows]

    def get_offer(self, offer_id: str) -> Optional[ServiceOffer]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM offers WHERE id = ?",
                (offer_id,),
            ).fetchone()
        return ServiceOffer.model_validate_json(row[0]) if row else None

    def delete_offer(self, offer_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM offers WHERE id = ?", (offer_id,))
        return cursor.rowcount > 0

    def save_scenario(self, scenario: OrderScenario) -> OrderScenario:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scenarios (id, payload) VALUES (?, ?)",
                (scenario.id, scenario.model_dump_json()),
            )
        return scenario

    def list_scenarios(self) -> List[OrderScenario]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM scenarios ORDER BY rowid").fetchall()
        return [OrderScenario.model_validate_json(row[0]) for row in rows]

    def get_scenario(self, scenario_id: str) -> Optional[OrderScenario]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM scenarios WHERE id = ?",
                (scenario_id,),
            ).fetchone()
        return OrderScenario.model_validate_json(row[0]) if row else None

    def delete_scenario(self, scenario_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
        return cursor.rowcount > 0

    def get_or_create_user(self, email: str) -> Dict[str, str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, email, created_at FROM users WHERE email = ?",
                (email,),
            ).fetchone()
            if row:
                return {"id": row[0], "email": row[1], "created_at": row[2]}

            user_id = f"user-{uuid4().hex[:12]}"
            created_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
                (user_id, email, created_at),
            )
        return {"id": user_id, "email": email, "created_at": created_at}

    def save_auth_code(self, email: str, code_hash: str, expires_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO auth_codes (email, code_hash, expires_at, attempts)
                VALUES (?, ?, ?, 0)
                """,
                (email, code_hash, expires_at),
            )

    def get_auth_code(self, email: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT email, code_hash, expires_at, attempts FROM auth_codes WHERE email = ?",
                (email,),
            ).fetchone()
        if not row:
            return None
        return {
            "email": row[0],
            "code_hash": row[1],
            "expires_at": row[2],
            "attempts": row[3],
        }

    def increment_auth_code_attempts(self, email: str) -> int:
        with self._connect() as conn:
            conn.execute(
                "UPDATE auth_codes SET attempts = attempts + 1 WHERE email = ?",
                (email,),
            )
            row = conn.execute(
                "SELECT attempts FROM auth_codes WHERE email = ?",
                (email,),
            ).fetchone()
        return int(row[0]) if row else 0

    def delete_auth_code(self, email: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM auth_codes WHERE email = ?", (email,))

    def create_session(self, token_hash: str, user_id: str, expires_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash, user_id, expires_at),
            )

    def get_user_by_session_token_hash(
        self, token_hash: str, now_iso: str
    ) -> Optional[Dict[str, str]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.id, u.email, u.created_at, s.expires_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            if row[3] < now_iso:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None
            return {"id": row[0], "email": row[1], "created_at": row[2]}

    def delete_session(self, token_hash: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def save_company_offer(self, user_id: str, offer: ServiceOffer) -> ServiceOffer:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO company_profiles (user_id, payload) VALUES (?, ?)",
                (user_id, offer.model_dump_json()),
            )
        return offer

    def get_company_offer(self, user_id: str) -> Optional[ServiceOffer]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM company_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return ServiceOffer.model_validate_json(row[0]) if row else None

    def get_credit_balance(self, user_id: str) -> int:
        """Возвращает текущий баланс кредитов пользователя (по умолчанию 0)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def list_credit_transactions(
        self, user_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Возвращает историю операций по кредитному счёту пользователя."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, delta, reason, reference_id, created_at
                FROM credit_ledger
                WHERE user_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [
            {
                "id": row[0],
                "delta": int(row[1]),
                "reason": row[2],
                "reference_id": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]

    def add_credits(
        self,
        user_id: str,
        amount: int,
        reason: str,
        reference_id: Optional[str] = None,
    ) -> int:
        """Начисляет положительное количество кредитов и возвращает новый баланс."""
        if amount <= 0:
            raise ValueError("Сумма начисления должна быть положительной")
        entry_id = f"cred-{uuid4().hex[:12]}"
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO credit_ledger (id, user_id, delta, reason, reference_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (entry_id, user_id, amount, reason, reference_id, created_at),
            )
            row = conn.execute(
                "SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def is_scenario_unlocked(self, user_id: str, scenario_id: str) -> bool:
        """Проверяет, оплачивал ли пользователь доступ к отчёту по сценарию."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM scenario_unlocks
                WHERE user_id = ? AND scenario_id = ?
                """,
                (user_id, scenario_id),
            ).fetchone()
        return row is not None

    def unlock_scenario_with_credit(
        self,
        user_id: str,
        scenario_id: str,
        cost: int = 1,
    ) -> tuple[bool, int]:
        """Атомарно списывает кредит и открывает сценарий (идемпотентно при повторе)."""
        if cost <= 0:
            raise ValueError("Стоимость разблокировки должна быть положительной")

        conn = self._connect()
        try:
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")

            existing = conn.execute(
                """
                SELECT 1 FROM scenario_unlocks
                WHERE user_id = ? AND scenario_id = ?
                """,
                (user_id, scenario_id),
            ).fetchone()
            balance_row = conn.execute(
                "SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            current_balance = int(balance_row[0]) if balance_row else 0

            if existing is not None:
                conn.execute("COMMIT")
                return False, current_balance

            if current_balance < cost:
                conn.execute("ROLLBACK")
                raise InsufficientCreditsError(current_balance, cost)

            now_iso = datetime.now(timezone.utc).isoformat()
            entry_id = f"cred-{uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO credit_ledger (id, user_id, delta, reason, reference_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (entry_id, user_id, -cost, "scenario_unlock", scenario_id, now_iso),
            )
            conn.execute(
                """
                INSERT INTO scenario_unlocks (user_id, scenario_id, unlocked_at)
                VALUES (?, ?, ?)
                """,
                (user_id, scenario_id, now_iso),
            )
            conn.execute("COMMIT")
            return True, current_balance - cost
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
