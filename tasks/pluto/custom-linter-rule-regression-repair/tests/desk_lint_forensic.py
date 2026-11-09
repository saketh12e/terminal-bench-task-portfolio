from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__import__("os").environ.get("APP_DIR", "/app"))
sys.path.insert(0, str(APP_DIR))

from lint_scan_physics import live_findings, rule_closure  # noqa: E402

DATA = APP_DIR / "data"
CORPUS = DATA / "corpus"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_physics_closure_includes_r005():
    registry = load_json(DATA / "rule_registry.json")
    graph = registry["rule_dependency_graph"]
    live = rule_closure(graph, registry["active_rules"])
    assert "R005" in live


def test_physics_finding_count():
    registry = load_json(DATA / "rule_registry.json")
    policy = load_json(DATA / "finding_binding_policy.json")
    rows = live_findings(CORPUS, registry, policy)
    ref = load_json(DATA / "reference_finding_grid.json")
    assert len(rows) == len(ref["expected_findings"])


def test_physics_matches_reference_keys():
    registry = load_json(DATA / "rule_registry.json")
    policy = load_json(DATA / "finding_binding_policy.json")
    rows = live_findings(CORPUS, registry, policy)
    ref = load_json(DATA / "reference_finding_grid.json")
    live_keys = {(r["file"], r["line"], r["rule_id"]) for r in rows}
    ref_keys = {(r["file"], r["line"], r["rule_id"]) for r in ref["expected_findings"]}
    assert live_keys == ref_keys


def test_physics_fingerprints_match_reference():
    registry = load_json(DATA / "rule_registry.json")
    policy = load_json(DATA / "finding_binding_policy.json")
    rows = live_findings(CORPUS, registry, policy)
    ref = load_json(DATA / "reference_finding_grid.json")
    by_key = {(r["file"], r["line"], r["rule_id"]): r for r in rows}
    for exp in ref["expected_findings"]:
        key = (exp["file"], exp["line"], exp["rule_id"])
        assert by_key[key]["fingerprint"] == exp["fingerprint"]
