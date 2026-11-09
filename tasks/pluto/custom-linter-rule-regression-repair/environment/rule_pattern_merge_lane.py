"""Broken regex line scan — misses AST structure and multiline patterns."""

from __future__ import annotations

import re
from pathlib import Path


def collect_findings(path: Path, enabled_rules: set[str], rule_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rel = path.name
    hits: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if "R002" in enabled_rules and re.search(r"\beval\s*\(", line):
            hits.append({"rule_id": "R002", "file": rel, "line": lineno, "col": 0})
        if "R001" in enabled_rules and re.search(r"\bexcept\s*:", line):
            hits.append({"rule_id": "R001", "file": rel, "line": lineno, "col": 0})
        if "R003" in enabled_rules and "password=" in line:
            hits.append({"rule_id": "R003", "file": rel, "line": lineno, "col": 0})
        if "R004" in enabled_rules and re.search(r"=\s*\[\s*\]", line):
            hits.append({"rule_id": "R004", "file": rel, "line": lineno, "col": 0})
    return hits
