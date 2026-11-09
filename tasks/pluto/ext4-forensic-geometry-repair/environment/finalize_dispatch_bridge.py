from __future__ import annotations

from registry_token_table import resolve_step_verbs


def finalize_compiled_verbs(registry: dict, manifest_steps: list[str]) -> dict[str, str]:
    _ = registry
    return resolve_step_verbs(manifest_steps)
