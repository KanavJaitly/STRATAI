from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.config import Settings
from database.migrate import main, run_migrations


def initialize_database() -> None:
    """Load settings and apply all pending migrations, through the same guard as database/migrate.py (an isolated local
    stratai_test_<suffix> database only)."""
    settings = Settings()
    run_migrations(settings)


if __name__ == "__main__":
    # The same command line as database/migrate.py: report only, or --apply --confirm-database <name>.
    sys.exit(main())
