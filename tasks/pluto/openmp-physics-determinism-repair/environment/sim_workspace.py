from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(os.environ.get("APP_DIR", "/app"))
DATA_DIR = APP_DIR / "data"
OUTPUT_DIR = APP_DIR / "output"
WORK_DIR = APP_DIR / "work"

SCENARIO_PATH = DATA_DIR / "sim_scenario.json"
REGISTRY_PATH = DATA_DIR / "sim_registry.json"
POLICY_PATH = DATA_DIR / "sim_policy.json"
STEP_MANIFEST_PATH = DATA_DIR / "sim_step_manifest.txt"
REFERENCE_DIGESTS_PATH = DATA_DIR / "reference_frame_digests.json"

FRAME_LEDGER_PATH = OUTPUT_DIR / "frame_digest_ledger.json"
TWIN_VERDICT_PATH = OUTPUT_DIR / "twin_run_verdict.json"
INTEGRATOR_AUDIT_PATH = OUTPUT_DIR / "integrator_audit.json"
SIM_ATTESTATION_PATH = OUTPUT_DIR / "sim_run_attestation.json"
SIM_SUMMARY_PATH = OUTPUT_DIR / "sim_run_summary.json"
REPLAY_TRACE_PATH = OUTPUT_DIR / "sim_replay_trace.log"

SUBJECT_SCENARIO_ID = "STACK-12B"
DEFAULT_FRAME_COUNT = 128
MIN_THREAD_BUCKETS = 2
