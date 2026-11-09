from __future__ import annotations

from pathlib import Path
from typing import Any

from rule_pattern_authority import collect_findings as authority_collect_findings


def dispatch_ast_scan(paths: list[Path], enabled_rules: set[str], rule_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(authority_collect_findings(path, enabled_rules, rule_index))
    return rows
