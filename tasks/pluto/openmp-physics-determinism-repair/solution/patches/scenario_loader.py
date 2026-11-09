from __future__ import annotations

import json

from sim_workspace import REGISTRY_PATH, STEP_MANIFEST_PATH


def load_step_verbs() -> dict[str, str]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return dict(registry.get("step_verbs", {}))


def resolve_step_verbs(steps: list[str]) -> dict[str, str]:
    verbs = load_step_verbs()
    return {step: verbs.get(step, "touched") for step in steps}
