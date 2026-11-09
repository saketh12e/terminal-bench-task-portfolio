from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(os.environ.get("APP_DIR", "/app"))
DATA_DIR = APP_ROOT / "data"
OUTPUT_DIR = APP_ROOT / "output"
WORK_DIR = APP_ROOT / "work"

SUBJECT_RUN_ID = "sparse-contraction-desk-001"

PATTERN_CATALOG_PATH = DATA_DIR / "sparse_pattern_catalog.json"
STALE_COALESCE_POLICY_PATH = DATA_DIR / "stale_coalesce_policy.json"
REFERENCE_GRADIENT_GRID_PATH = DATA_DIR / "reference_gradient_grid.json"
TRAIN_STAGE_AUTHORITY_PATH = DATA_DIR / "train_stage_authority.json"
GRADIENT_BINDING_POLICY_PATH = DATA_DIR / "gradient_binding_policy.json"

WORK_TRAIN_POLICY_PATH = WORK_DIR / "sparse_train_policy.json"

GRADIENT_PARITY_REPORT_PATH = OUTPUT_DIR / "gradient_parity_report.json"
TRAINING_LOSS_CURVE_PATH = OUTPUT_DIR / "training_loss_curve.json"
BACKWARD_TRACE_PATH = OUTPUT_DIR / "backward_trace.log"
GRADIENT_BINDING_AUDIT_PATH = OUTPUT_DIR / "gradient_binding_audit.json"
SPARSE_COVERAGE_SNAPSHOT_PATH = OUTPUT_DIR / "sparse_coverage_snapshot.json"
TRAIN_INTEGRITY_RECORD_PATH = OUTPUT_DIR / "train_integrity_record.json"
TRAIN_STAGE_TARGETS_PATH = OUTPUT_DIR / "train_stage_targets.txt"
TRAIN_TRACE_PATH = OUTPUT_DIR / "train_trace.log"
