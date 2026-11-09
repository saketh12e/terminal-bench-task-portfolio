from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(os.environ.get("APP_DIR", "/app"))
DATA_DIR = APP_DIR / "data"
OUTPUT_DIR = APP_DIR / "output"
WORK_DIR = APP_DIR / "work"

DISK_IMAGE_PATH = DATA_DIR / "incident_disk.img"
LAYOUT_REGISTRY_PATH = DATA_DIR / "layout_registry.json"
STALE_LAYOUT_POLICY_PATH = DATA_DIR / "stale_layout_policy.json"
DESK_LANE_AUTHORITY_PATH = DATA_DIR / "desk_lane_authority.json"
WORK_LANE_OVERLAY_PATH = DATA_DIR / "work_lane_overlay.json"
REPAIR_MANIFEST_PATH = DATA_DIR / "repair_step_manifest.txt"
REFERENCE_GEOMETRY_PATH = DATA_DIR / "reference_geometry.json"

RECONSTRUCTED_MBR_PATH = OUTPUT_DIR / "reconstructed_mbr.bin"
PATCHED_DISK_PATH = OUTPUT_DIR / "patched_disk.img"
GEOMETRY_ATTESTATION_PATH = OUTPUT_DIR / "geometry_attestation.json"
CARVE_VERDICT_PATH = OUTPUT_DIR / "carve_verdict.json"
FSCK_READINESS_PATH = OUTPUT_DIR / "fsck_readiness.json"
REPAIR_SUMMARY_PATH = OUTPUT_DIR / "repair_summary.json"
REPAIR_SECTOR_TRACE_PATH = OUTPUT_DIR / "repair_sector_trace.log"

SUBJECT_CASE_ID = "DF-INC-09"
SECTOR_SIZE = 512
PARTITION_TYPE_LINUX = 0x83
