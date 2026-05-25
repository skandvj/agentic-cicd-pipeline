"""Fail fast when production deployments are missing live configuration."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.runtime.settings import ProductionConfigurationError, load_settings, validate_production_settings


def main(repo_root: Path | None = None) -> int:
    settings = load_settings()
    resolved_root = repo_root or Path.cwd()
    try:
        validate_production_settings(resolved_root, settings)
    except ProductionConfigurationError as exc:
        print(f"Production configuration check failed: {exc}", file=sys.stderr)
        return 1

    if not settings.is_production:
        print("Production configuration check skipped because RUNTIME_MODE=demo.")
        return 0

    print(f"Production configuration check passed for environment={settings.environment}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
