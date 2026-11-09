from __future__ import annotations

from binding_lane_resolver import compiled_verbs


def finalize_compiled_verbs(registry: dict, manifest_steps: list[str]) -> dict[str, str]:
    _ = manifest_steps
    return compiled_verbs(registry)
