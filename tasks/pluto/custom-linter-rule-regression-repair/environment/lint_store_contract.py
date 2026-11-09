from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(os.environ.get("APP_DIR", "/app"))
DATA_DIR = APP_DIR / "data"
CORPUS_DIR = DATA_DIR / "corpus"
OUTPUT_DIR = APP_DIR / "output"
WORK_DIR = APP_DIR / "work"

SUBJECT_CASE_ID = "LINT-REG-09"

RULE_REGISTRY_PATH = DATA_DIR / "rule_registry.json"
STALE_RULE_PACK_PATH = DATA_DIR / "stale_rule_pack.json"
REFERENCE_FINDING_GRID_PATH = DATA_DIR / "reference_finding_grid.json"
SCAN_STAGE_AUTHORITY_PATH = DATA_DIR / "scan_stage_authority.json"
SCAN_STAGE_TARGETS_PATH = DATA_DIR / "scan_stage_targets.txt"
FINDING_BINDING_POLICY_PATH = DATA_DIR / "finding_binding_policy.json"

LINT_SCAN_REPORT_PATH = OUTPUT_DIR / "lint_scan_report.json"
RULE_COVERAGE_SNAPSHOT_PATH = OUTPUT_DIR / "rule_coverage_snapshot.json"
FINDING_BINDING_AUDIT_PATH = OUTPUT_DIR / "finding_binding_audit.json"
LINT_INTEGRITY_RECORD_PATH = OUTPUT_DIR / "lint_integrity_record.json"
SCAN_SUMMARY_PATH = OUTPUT_DIR / "scan_summary.json"
SCAN_TRACE_PATH = OUTPUT_DIR / "scan_trace.log"

WORK_LINT_POLICY_PATH = WORK_DIR / "lint_reconcile_policy.json"
