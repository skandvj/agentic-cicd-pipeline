"""Detect changed agents from git diff, falling back to all agents."""

from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        diff = subprocess.check_output(
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        diff = ""
    changed = set()
    for line in diff.splitlines():
        parts = Path(line).parts
        if len(parts) >= 2 and parts[0] == "agents":
            changed.add(parts[1])
    if not changed:
        changed = {path.name for path in (root / "agents").iterdir() if (path / "agent.yaml").exists()}
    print("\n".join(sorted(changed)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
