from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.config import Settings
from database.connection import Database, DatabaseConfig


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _migration_files() -> Iterable[Path]:
    """Return migration SQL files in application order."""
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def run_migrations(settings: Settings) -> None:
    """Apply every migration under migrations/ that isn't already recorded as applied."""
    database = Database(DatabaseConfig(settings.database_url))

    with database.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS migrations_applied (
                migration_file TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

        for migration in _migration_files():
            migration_name = migration.name
            cursor.execute(
                "SELECT 1 FROM migrations_applied WHERE migration_file = %s",
                (migration_name,),
            )
            if cursor.fetchone() is not None:
                continue

            sql = migration.read_text(encoding="utf-8")
            cursor.execute(sql)
            cursor.execute(
                "INSERT INTO migrations_applied (migration_file) VALUES (%s)",
                (migration_name,),
            )


if __name__ == "__main__":
    settings = Settings()
    run_migrations(settings)
