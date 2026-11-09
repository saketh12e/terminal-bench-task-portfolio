from __future__ import annotations

import json
from pathlib import Path

from sim_workspace import POLICY_PATH, STEP_MANIFEST_PATH


def load_step_verbs() -> dict[str, str]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    return dict(policy.get("step_verbs", {}))


def resolve_step_verbs(steps: list[str]) -> dict[str, str]:
    verbs = load_step_verbs()
    return {step: verbs.get(step, "touched") for step in steps}
