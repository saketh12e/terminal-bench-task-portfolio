from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(os.environ.get("APP_DIR", "/app"))
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from forensic_workspace import (  # noqa: E402
    GEOMETRY_ATTESTATION_PATH,
    LAYOUT_REGISTRY_PATH,
    PATCHED_DISK_PATH,
    RECONSTRUCTED_MBR_PATH,
    REFERENCE_GEOMETRY_PATH,
    REPAIR_SUMMARY_PATH,
)

PYTHON_BIN = os.environ.get("PYTHON_BIN", "python")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_pipeline() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON_BIN, "recovery_batch_runner.py"],
        cwd=APP_DIR,
        text=True,
        capture_output=True,
        timeout=120,
    )


def ensure_run() -> None:
    result = run_pipeline()
    assert result.returncode == 0, result.stdout + result.stderr


def reference() -> dict:
    return load_json(REFERENCE_GEOMETRY_PATH)


def live_reference_ok(disk: bytes, registry: dict, ref: dict) -> bool:
    entry_off = int(registry["mbr_partition_entry_offset"])
    lba_start = struct.unpack_from("<I", disk, entry_off + 8)[0]
    sector_count = struct.unpack_from("<I", disk, entry_off + 12)[0]
    backup_off = int(registry["backup_superblock_offset"])
    blocks_count = struct.unpack_from("<I", disk, backup_off + 0x4)[0]
    inodes_count = struct.unpack_from("<I", disk, backup_off + 0x28)[0]
    carve_off = int(registry["carve_offset"])
    carve_len = int(registry["carve_length"])
    carve_ok = hashlib.sha256(disk[carve_off : carve_off + carve_len]).hexdigest() == ref["carve_sha256"]
    mbr_ok = disk[510] == 0x55 and disk[511] == 0xAA
    magic = struct.unpack_from("<H", disk, backup_off + 0x38)[0]
    block_size = struct.unpack_from("<I", disk, backup_off + 0x18)[0]
    sb_ok = magic == 0xEF53 and block_size == 4096
    mount_ready = mbr_ok and sb_ok and carve_ok
    fsck_ready = mount_ready and carve_ok
    return (
        lba_start == int(ref["lba_start"])
        and sector_count == int(ref["sector_count"])
        and blocks_count == int(ref["blocks_count"])
        and inodes_count == int(ref["inodes_count"])
        and carve_ok
        and mbr_ok
        and fsck_ready
    )


def test_desk_carve_digest_matches_reference():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    disk = PATCHED_DISK_PATH.read_bytes()
    off = int(reg["carve_offset"])
    ln = int(reg["carve_length"])
    digest = hashlib.sha256(disk[off : off + ln]).hexdigest()
    assert digest == reference()["carve_sha256"]


def test_desk_backup_blocks_match_reference():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    disk = PATCHED_DISK_PATH.read_bytes()
    blocks = struct.unpack_from("<I", disk, int(reg["backup_superblock_offset"]) + 0x4)[0]
    assert blocks == reference()["blocks_count"]


def test_desk_mbr_lba_matches_reference():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    mbr = RECONSTRUCTED_MBR_PATH.read_bytes()
    entry_off = int(reg["mbr_partition_entry_offset"])
    lba = struct.unpack_from("<I", mbr, entry_off + 8)[0]
    assert lba == reference()["lba_start"]


def test_summary_reference_ok_matches_desk_probe():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    ref = reference()
    disk = PATCHED_DISK_PATH.read_bytes()
    expected = live_reference_ok(disk, reg, ref)
    assert load_json(REPAIR_SUMMARY_PATH)["reference_geometry_ok"] is expected


def test_desk_inodes_match_reference():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    disk = PATCHED_DISK_PATH.read_bytes()
    inodes = struct.unpack_from("<I", disk, int(reg["backup_superblock_offset"]) + 0x28)[0]
    assert inodes == reference()["inodes_count"]


def test_desk_probe_matches_attestation_flag():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    ref = reference()
    disk = PATCHED_DISK_PATH.read_bytes()
    expected = live_reference_ok(disk, reg, ref)
    assert load_json(GEOMETRY_ATTESTATION_PATH)["disk_probe_ok"] is expected


def test_finalize_digest_matches_post_rewrite_trace():
    ensure_run()
    import hashlib

    digest = hashlib.sha256(
        (APP_DIR / "output/repair_sector_trace.log").read_bytes()
    ).hexdigest()
    assert load_json(REPAIR_SUMMARY_PATH)["trace_chain_digest"] == digest
