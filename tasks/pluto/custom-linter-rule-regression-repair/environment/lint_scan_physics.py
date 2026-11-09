"""Independent AST lint replay for verifier physics (not the batch runner)."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any


def rule_closure(graph: dict[str, Any], roots: list[str]) -> set[str]:
    edges = graph.get("edges", [])
    adj: dict[str, list[str]] = {}
    for edge in edges:
        adj.setdefault(edge["from"], []).append(edge["to"])
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adj.get(node, []))
    return seen


def finding_fingerprint(rule_id: str, file_name: str, line: int, col: int, policy: dict[str, Any]) -> str:
    delim = policy.get("segment_delimiter", "|")
    names = policy["segment_names"]
    values = {
        "rule_id": rule_id,
        "file": file_name,
        "line": str(line),
        "col": str(col),
    }
    material = delim.join(values[n] for n in names)
    length = int(policy.get("digest_hex_length", 16))
    return hashlib.sha256(material.encode()).hexdigest()[:length]


def _line_col(node: ast.AST, source: str) -> tuple[int, int]:
    return node.lineno or 1, node.col_offset or 0


def _scan_eval(tree: ast.AST, rel: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "eval":
            line, col = _line_col(node, "")
            out.append({"rule_id": "R002", "file": rel, "line": line, "col": col})
    return out


def _scan_bare_except(tree: ast.AST, rel: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            line, col = _line_col(node, "")
            out.append({"rule_id": "R001", "file": rel, "line": line, "col": col})
    return out


def _scan_mutable_default(tree: ast.AST, rel: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default, arg in zip(reversed(node.args.defaults), reversed(node.args.args)):
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    line, col = _line_col(arg, "")
                    out.append({"rule_id": "R004", "file": rel, "line": line, "col": col})
    return out


def _scan_secret_literal(tree: ast.AST, rel: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "password=" in node.value:
            line, col = _line_col(node, "")
            out.append({"rule_id": "R003", "file": rel, "line": line, "col": col})
    return out


def _scan_pickle_loads(tree: ast.AST, rel: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "loads" and isinstance(node.func.value, ast.Name) and node.func.value.id == "pickle":
                line, col = _line_col(node, "")
                out.append({"rule_id": "R005", "file": rel, "line": line, "col": col})
    return out


_SCANNERS = {
    "eval_call": _scan_eval,
    "bare_except": _scan_bare_except,
    "mutable_default": _scan_mutable_default,
    "secret_literal": _scan_secret_literal,
    "pickle_loads": _scan_pickle_loads,
}


def scan_file(path: Path, enabled_rules: set[str], rule_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rel = path.name
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=rel)
    hits: list[dict[str, Any]] = []
    for rule_id in sorted(enabled_rules):
        meta = rule_index.get(rule_id)
        if not meta:
            continue
        kind = meta.get("pattern_kind", "")
        scanner = _SCANNERS.get(kind)
        if not scanner:
            continue
        hits.extend(scanner(tree, rel))
    return hits


def live_findings(corpus_dir: Path, registry: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
    graph = registry.get("rule_dependency_graph", {})
    roots = list(registry.get("active_rules", []))
    enabled = rule_closure(graph, roots)
    rule_index = {r["rule_id"]: r for r in registry.get("rules", [])}
    rows: list[dict[str, Any]] = []
    for path in sorted(corpus_dir.glob("*.py")):
        for hit in scan_file(path, enabled, rule_index):
            fp = finding_fingerprint(hit["rule_id"], hit["file"], hit["line"], hit["col"], policy)
            rows.append(
                {
                    "rule_id": hit["rule_id"],
                    "file": hit["file"],
                    "line": hit["line"],
                    "col": hit["col"],
                    "fingerprint": fp,
                    "finding_stable": True,
                }
            )
    rows.sort(key=lambda r: (r["file"], r["line"], r["col"], r["rule_id"]))
    return rows


def rule_graph_digest(findings: list[dict[str, Any]]) -> str:
    material = []
    for row in findings:
        material.append(
            "|".join(
                [
                    str(row.get("rule_id", "")),
                    str(row.get("file", "")),
                    str(row.get("line", "")),
                    str(row.get("col", "")),
                    str(row.get("fingerprint", "")),
                    str(row.get("finding_stable", False)),
                ]
            )
        )
    return hashlib.sha256("\n".join(material).encode()).hexdigest()
