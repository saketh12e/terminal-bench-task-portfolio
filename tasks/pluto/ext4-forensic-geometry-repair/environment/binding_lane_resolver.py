from __future__ import annotations

import json

from forensic_workspace import DATA_DIR, WORK_LANE_OVERLAY_PATH


def compiled_verbs(registry: dict) -> dict[str, str]:
    lane_name = str(registry["binding_lane"])
    if not lane_name.endswith(".json"):
        lane_name = f"{lane_name}.json"
    lane = json.loads((DATA_DIR / lane_name).read_text(encoding="utf-8"))
    merged = dict(lane.get("compiled_step_verbs", {}))
    overlay = json.loads(WORK_LANE_OVERLAY_PATH.read_text(encoding="utf-8"))
    merged.update(overlay.get("verb_overrides", {}))
    return merged
