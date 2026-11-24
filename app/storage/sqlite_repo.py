import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_offers (
                    scenario_id TEXT NOT NULL,
                    offer_id TEXT NOT NULL,
                    PRIMARY KEY (scenario_id, offer_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS search_cache (
                    query_hash TEXT PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            cols = {
                row[1] for row in conn.execute("PRAGMA table_info(offers)").fetchall()
            }
            if "updated_at" not in cols:
                conn.execute("ALTER TABLE offers ADD COLUMN updated_at TEXT")
            scen_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(scenarios)").fetchall()
            }
            if "user_id" not in scen_cols:
                conn.execute("ALTER TABLE scenarios ADD COLUMN user_id TEXT")
            if "created_at" not in scen_cols:
                conn.execute("ALTER TABLE scenarios ADD COLUMN created_at TEXT")

    def save_offer(self, offer: ServiceOffer) -> ServiceOffer:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO offers (id, payload, updated_at) VALUES (?, ?, ?)",
                (offer.id, offer.model_dump_json(), now_iso),
            )
        return offer

    def list_fresh_offers_by_url(self, max_age_days: int = 14) -> Dict[str, ServiceOffer]:
        """Возвращает свежие предложения по source_url с учётом TTL."""
        cutoff_iso = (
            datetime.now(timezone.utc) - timedelta(days=max_age_days)
        ).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload, updated_at FROM offers ORDER BY rowid DESC"
            ).fetchall()
        by_url: Dict[str, ServiceOffer] = {}
        for payload, updated_at in rows:
            if updated_at is not None and updated_at < cutoff_iso:
                continue
            offer = ServiceOffer.model_validate_json(payload)
            if offer.source_url and offer.source_url not in by_url:
                by_url[offer.source_url] = offer
        return by_url

    @staticmethod
    def _hash_query(query_text: str) -> str:
        normalized = " ".join(query_text.strip().lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get_cached_search(self, query_text: str) -> Optional[List[Dict[str, Any]]]:
        """Возвращает закэшированную выдачу поиска, если она ещё не устарела."""
        q_hash = self._hash_query(query_text)
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload, expires_at FROM search_cache WHERE query_hash = ?",
                (q_hash,),
            ).fetchone()
            if not row:
                return None
            if row[1] < now_iso:
                conn.execute(
                    "DELETE FROM search_cache WHERE query_hash = ?", (q_hash,)
                )
                return None
        return json.loads(row[0])

    def save_cached_search(
        self,
        query_text: str,
        candidates: List[Dict[str, Any]],
        ttl_hours: int = 24,
    ) -> None:
        """Сохраняет результаты поиска в кэш SQLite с TTL."""
        q_hash = self._hash_query(query_text)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        ).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO search_cache (query_hash, query_text, payload, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    q_hash,
                    query_text,
                    json.dumps(candidates, ensure_ascii=False),
                    expires_at,
                ),
            )

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

    def save_scenario(
        self, scenario: OrderScenario, user_id: Optional[str] = None
    ) -> OrderScenario:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scenarios (id, payload, user_id, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    user_id = COALESCE(excluded.user_id, scenarios.user_id),
                    created_at = COALESCE(scenarios.created_at, excluded.created_at)
                """,
                (scenario.id, scenario.model_dump_json(), user_id, now_iso),
            )
        return scenario

    def list_recent_scenarios_for_user(
        self, user_id: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Возвращает последние сценарии пользователя со статусом открытия отчёта."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.id,
                    s.payload,
                    s.created_at,
                    CASE WHEN su.scenario_id IS NOT NULL THEN 1 ELSE 0 END AS is_unlocked
                FROM scenarios s
                LEFT JOIN scenario_unlocks su
                    ON su.scenario_id = s.id AND su.user_id = ?
                WHERE s.user_id = ?
                ORDER BY s.rowid DESC
                LIMIT ?
                """,
                (user_id, user_id, limit),
            ).fetchall()
        items: List[Dict[str, Any]] = []
        for scen_id, payload, created_at, is_unlocked in rows:
            scenario = OrderScenario.model_validate_json(payload)
            items.append(
                {
                    "id": scen_id,
                    "title": scenario.title,
                    "city": scenario.city,
                    "is_online": scenario.is_online,
                    "created_at": created_at,
                    "is_unlocked": bool(is_unlocked),
                    "scenario": scenario.model_dump(mode="json"),
                }
            )
        return items

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
            conn.execute(
                "DELETE FROM scenario_offers WHERE scenario_id = ?", (scenario_id,)
            )
            cursor = conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
        return cursor.rowcount > 0

    def link_offer_to_scenario(self, scenario_id: str, offer_id: str) -> None:
        """Привязывает предложение к конкретному сценарию."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO scenario_offers (scenario_id, offer_id) VALUES (?, ?)",
                (scenario_id, offer_id),
            )

    def list_offers_for_scenario(self, scenario_id: str) -> List[ServiceOffer]:
        """Возвращает предложения, привязанные к конкретному сценарию."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT o.payload
                FROM offers o
                JOIN scenario_offers so ON so.offer_id = o.id
                WHERE so.scenario_id = ?
                ORDER BY o.rowid ASC
                """,
                (scenario_id,),
            ).fetchall()
        return [ServiceOffer.model_validate_json(row[0]) for row in rows]

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
