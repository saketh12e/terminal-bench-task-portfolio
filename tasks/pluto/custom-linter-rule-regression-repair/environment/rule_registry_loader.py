from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_rule_registry(registry_path: Path, stale_pack_path: Path) -> dict[str, Any]:
    stale = json.loads(stale_pack_path.read_text(encoding="utf-8"))
    if stale.get("prefer_stale_rules", True):
        return {
            "case_id": "STALE",
            "active_rules": stale.get("active_rules", []),
            "rules": stale.get("rules", []),
            "rule_dependency_graph": {"edges": [], "expected_closure": stale.get("active_rules", [])},
        }
    return json.loads(registry_path.read_text(encoding="utf-8"))
