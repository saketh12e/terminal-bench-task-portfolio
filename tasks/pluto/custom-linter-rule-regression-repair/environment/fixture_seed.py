#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from lint_scan_physics import live_findings, rule_closure
from lint_store_contract import (
    CORPUS_DIR,
    DATA_DIR,
    FINDING_BINDING_POLICY_PATH,
    OUTPUT_DIR,
    REFERENCE_FINDING_GRID_PATH,
    RULE_REGISTRY_PATH,
    SCAN_STAGE_AUTHORITY_PATH,
    SCAN_STAGE_TARGETS_PATH,
    STALE_RULE_PACK_PATH,
    SUBJECT_CASE_ID,
    WORK_DIR,
    WORK_LINT_POLICY_PATH,
)

CORPUS_FILES = {
    "api_handler.py": '''"""HTTP helpers."""
def execute(payload):
    return eval(payload)
''',
    "auth_utils.py": '''def read_config():
    try:
        return open("/tmp/x").read()
    except:
        return ""
''',
    "config_loader.py": '''def merge(items=[]):
    return items
''',
    "worker.py": '''CFG = {"password=admin:sekret"}
''',
    "pickle_risk.py": '''import pickle

def load_blob(data):
    return pickle.loads(data)
''',
    "clean_module.py": '''def ok():
    return 1 + 1
''',
}


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    for name, body in CORPUS_FILES.items():
        (CORPUS_DIR / name).write_text(body, encoding="utf-8")

    registry = {
        "case_id": SUBJECT_CASE_ID,
        "active_rules": ["R001", "R002", "R003", "R004"],
        "rules": [
            {"rule_id": "R001", "pattern_kind": "bare_except", "severity": "high"},
            {"rule_id": "R002", "pattern_kind": "eval_call", "severity": "critical"},
            {"rule_id": "R003", "pattern_kind": "secret_literal", "severity": "high"},
            {"rule_id": "R004", "pattern_kind": "mutable_default", "severity": "medium"},
            {"rule_id": "R005", "pattern_kind": "pickle_loads", "severity": "critical"},
        ],
        "rule_dependency_graph": {
            "edges": [{"from": "R001", "to": "R005"}],
            "expected_closure": ["R001", "R002", "R003", "R004", "R005"],
        },
    }
    RULE_REGISTRY_PATH.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    STALE_RULE_PACK_PATH.write_text(
        json.dumps(
            {
                "prefer_stale_rules": True,
                "active_rules": ["R001", "R003"],
                "rules": [
                    {"rule_id": "R001", "pattern_kind": "bare_except", "severity": "low"},
                    {"rule_id": "R003", "pattern_kind": "secret_literal", "severity": "low"},
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    FINDING_BINDING_POLICY_PATH.write_text(
        json.dumps(
            {
                "digest_algorithm": "sha256",
                "digest_hex_length": 16,
                "segment_names": ["rule_id", "file", "line", "col"],
                "segment_delimiter": "|",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    policy = json.loads(FINDING_BINDING_POLICY_PATH.read_text(encoding="utf-8"))
    expected = live_findings(CORPUS_DIR, registry, policy)
    REFERENCE_FINDING_GRID_PATH.write_text(
        json.dumps(
            {
                "case_id": SUBJECT_CASE_ID,
                "corpus_files": sorted(CORPUS_FILES.keys()),
                "expected_findings": expected,
                "rule_dependency_graph": registry["rule_dependency_graph"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    SCAN_STAGE_TARGETS_PATH.write_text(
        "expand_corpus_manifest\ncompile_ast_visit_plan\nemit_finding_binding_audit\npublish_lint_scan_report\nseal_rule_closeout\n",
        encoding="utf-8",
    )
    SCAN_STAGE_AUTHORITY_PATH.write_text(
        json.dumps(
            {
                "stage_actions": {
                    "expand_corpus_manifest": "resolve_corpus_paths",
                    "compile_ast_visit_plan": "sync_ast_visitors",
                    "emit_finding_binding_audit": "write_binding_audit",
                    "publish_lint_scan_report": "publish_scan_report",
                    "seal_rule_closeout": "seal_integrity_record",
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    WORK_LINT_POLICY_PATH.write_text(
        json.dumps({"force_scan_clean": False, "prefer_regex_merge_lane": True}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
