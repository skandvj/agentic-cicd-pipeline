"""Validate all agent.yaml files against the runtime schema."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.runtime.models import AgentConfig


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    config_paths = sorted((root / "agents").glob("*/agent.yaml"))
    if not config_paths:
        print("no agent configs found", file=sys.stderr)
        return 1
    failed = False
    for path in config_paths:
        try:
            AgentConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (ValidationError, yaml.YAMLError) as exc:
            failed = True
            print(f"invalid {path}: {exc}", file=sys.stderr)
        else:
            print(f"valid {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
