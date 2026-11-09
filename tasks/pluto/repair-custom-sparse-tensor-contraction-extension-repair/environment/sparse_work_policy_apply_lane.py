from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def effective_work_policy(work_policy: dict[str, Any], repair_plan_path: Path | None) -> dict[str, Any]:
    """Broken: ignores repair plan; seeded work policy always wins."""
    return dict(work_policy)
