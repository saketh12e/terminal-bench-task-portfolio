"""Authoritative AST pattern visitors (correct — not wired by broken dispatch bridge)."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from lint_scan_physics import _SCANNERS


def collect_findings(path: Path, enabled_rules: set[str], rule_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rel = path.name
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    hits: list[dict[str, Any]] = []
    for rule_id in sorted(enabled_rules):
        meta = rule_index.get(rule_id)
        if not meta:
            continue
        scanner = _SCANNERS.get(meta.get("pattern_kind", ""))
        if not scanner:
            continue
        hits.extend(scanner(tree, rel))
    return hits
