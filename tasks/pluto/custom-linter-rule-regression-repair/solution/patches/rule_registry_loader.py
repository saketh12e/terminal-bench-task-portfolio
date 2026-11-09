from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_rule_registry(registry_path: Path, stale_pack_path: Path) -> dict[str, Any]:
    return json.loads(registry_path.read_text(encoding="utf-8"))
