from __future__ import annotations

import json

from forensic_workspace import DATA_DIR


def compiled_verbs(registry: dict) -> dict[str, str]:
    lane_name = str(registry["binding_lane"])
    if not lane_name.endswith(".json"):
        lane_name = f"{lane_name}.json"
    lane = json.loads((DATA_DIR / lane_name).read_text(encoding="utf-8"))
    return dict(lane.get("compiled_step_verbs", {}))
