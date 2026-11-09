from __future__ import annotations

from typing import Any


def closure_rules(graph: dict[str, Any], roots: list[str]) -> set[str]:
    edges = graph.get("edges", [])
    reachable: set[str] = set(roots)
    frontier = set(roots)
    for edge in edges:
        if edge["from"] in frontier:
            reachable.add(edge["to"])
    return reachable
