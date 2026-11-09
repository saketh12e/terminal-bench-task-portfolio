from __future__ import annotations

import json

from forensic_workspace import LAYOUT_REGISTRY_PATH


def load_step_verbs() -> dict[str, str]:
    registry = json.loads(LAYOUT_REGISTRY_PATH.read_text(encoding="utf-8"))
    return dict(registry.get("step_verbs", {}))


def resolve_step_verbs(steps: list[str]) -> dict[str, str]:
    verbs = load_step_verbs()
    return {step: verbs.get(step, "touched") for step in steps}
