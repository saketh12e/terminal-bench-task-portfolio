from __future__ import annotations

import json
from pathlib import Path


def write_geometry_attestation(
    path: Path,
    *,
    case_id: str,
    lba_start: int,
    sector_count: int,
    blocks_count: int,
    inodes_count: int,
    fsck_ready: bool,
) -> dict:
    payload = {
        "case_id": case_id,
        "repair_complete": True,
        "lba_start": lba_start,
        "sector_count": sector_count,
        "blocks_count": blocks_count,
        "inodes_count": inodes_count,
        "fsck_ready": fsck_ready,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_carve_verdict(path: Path, *, match: bool, expected: str, actual: str) -> dict:
    payload = {
        "carve_hash_match": match,
        "expected_sha256": expected,
        "actual_sha256": actual,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_fsck_readiness(path: Path, *, ready: bool, mount_ready: bool) -> dict:
    payload = {"fsck_ready": ready, "mount_ready": mount_ready}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload
