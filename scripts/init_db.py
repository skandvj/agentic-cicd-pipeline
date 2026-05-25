"""Initialize production trace and eval tables."""

from __future__ import annotations

from src.dashboard.traces import PostgresTraceStore
from src.runtime.settings import load_settings


def main() -> None:
    settings = load_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required to initialize the production database")
    PostgresTraceStore(settings.database_url)
    print("Database schema initialized.")


if __name__ == "__main__":
    main()
