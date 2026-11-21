import os
import sqlite3
from pathlib import Path
from typing import List, Optional

from app.models import OrderScenario, ServiceOffer


def resolve_db_path(database_url: Optional[str] = None) -> str:
    """Преобразует DATABASE_URL вида sqlite:///... в путь к файлу SQLite."""
    raw = database_url or os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
    if raw.startswith("sqlite:///"):
        return raw[len("sqlite:///") :]
    return raw


class SQLiteRepository:
    """Изолированный репозиторий для хранения предложений и сценариев в SQLite."""

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
