from __future__ import annotations

import json

from forensic_workspace import STALE_LAYOUT_POLICY_PATH


def resolve_step_verbs(registry: dict, steps: list[str]) -> dict[str, str]:
    _ = registry
    policy = json.loads(STALE_LAYOUT_POLICY_PATH.read_text(encoding="utf-8"))
    verbs = dict(policy.get("step_verbs", {}))
    return {step: verbs.get(step, "touched") for step in steps}
