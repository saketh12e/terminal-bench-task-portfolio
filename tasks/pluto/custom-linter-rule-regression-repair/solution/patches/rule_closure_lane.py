from __future__ import annotations

from typing import Any

from lint_scan_physics import rule_closure


def closure_rules(graph: dict[str, Any], roots: list[str]) -> set[str]:
    return rule_closure(graph, roots)
