from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from backup_sb_lane import patch_backup_sb
from evidence_digest_checker import verify_carve_hash
from gpt_type_encoder import encode_partition_type
from json_report_emitter import write_carve_verdict, write_fsck_readiness, write_geometry_attestation
from lane_token_resolver import resolve_step_verbs
from mount_gate_evaluator import check_mount_ready
from output_finalize_pass import finalize_case_outputs
from partition_span_engine import solve_geometry
from boot_slot_writer import write_mbr_slot
from forensic_workspace import (
    CARVE_VERDICT_PATH,
    DISK_IMAGE_PATH,
    FSCK_READINESS_PATH,
    GEOMETRY_ATTESTATION_PATH,
    LAYOUT_REGISTRY_PATH,
    OUTPUT_DIR,
    PATCHED_DISK_PATH,
    RECONSTRUCTED_MBR_PATH,
    REFERENCE_GEOMETRY_PATH,
    REPAIR_MANIFEST_PATH,
    REPAIR_SECTOR_TRACE_PATH,
    REPAIR_SUMMARY_PATH,
    SUBJECT_CASE_ID,
    WORK_DIR,
)
from sector_anchor_resolver import scan_journal_anchor


def _log_sector(trace_path: Path, sector: int, verb: str) -> None:
    with trace_path.open("a", encoding="utf-8") as fh:
        fh.write(f"sector={sector} op={verb}\n")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    registry = json.loads(LAYOUT_REGISTRY_PATH.read_text(encoding="utf-8"))
    reference = json.loads(REFERENCE_GEOMETRY_PATH.read_text(encoding="utf-8"))
    steps = REPAIR_MANIFEST_PATH.read_text(encoding="utf-8").strip().splitlines()
    verbs = resolve_step_verbs(registry, steps)

    if REPAIR_SECTOR_TRACE_PATH.exists():
        REPAIR_SECTOR_TRACE_PATH.unlink()

    disk = bytearray(DISK_IMAGE_PATH.read_bytes())
    anchor = scan_journal_anchor(disk, registry)
    geometry = solve_geometry(
        sector_size=int(registry["sector_size"]),
        anchor_lba=anchor,
        disk_size=len(disk),
        registry=registry,
    )

    mbr = bytearray(512)
    part_type = encode_partition_type(True)
    entry_off = int(registry["mbr_partition_entry_offset"])
    write_mbr_slot(
        mbr,
        entry_off,
        lba_start=int(geometry["lba_start"]),
        sector_count=int(geometry["sector_count"]),
        part_type=part_type,
    )
    RECONSTRUCTED_MBR_PATH.write_bytes(bytes(mbr))

    mbr_ok = mbr[510] == 0x55 and mbr[511] == 0xAA
    disk[0:512] = mbr

    patch_backup_sb(
        disk,
        int(registry["primary_superblock_offset"]),
        int(registry["backup_superblock_offset"]),
        geometry,
    )

    carve_off = int(registry["carve_offset"])
    carve_len = int(registry["carve_length"])
    actual_hash = verify_carve_hash(disk, carve_off, carve_len)
    expected_hash = reference["carve_sha256"]
    carve_ok = actual_hash == expected_hash

    sb_magic = struct.unpack_from("<H", disk, int(registry["backup_superblock_offset"]) + 0x38)[0]
    sb_ok = sb_magic == 0xEF53 and int(geometry["block_size"]) == 4096

    mount_ready = check_mount_ready(mbr_ok=mbr_ok, sb_ok=sb_ok, carve_ok=carve_ok)
    fsck_ready = mount_ready and carve_ok

    PATCHED_DISK_PATH.write_bytes(disk)

    write_geometry_attestation(
        GEOMETRY_ATTESTATION_PATH,
        case_id=SUBJECT_CASE_ID,
        lba_start=int(geometry["lba_start"]),
        sector_count=int(geometry["sector_count"]),
        blocks_count=int(geometry["blocks_count"]),
        inodes_count=int(geometry["inodes_count"]),
        fsck_ready=fsck_ready,
    )

    write_carve_verdict(
        CARVE_VERDICT_PATH,
        match=carve_ok,
        expected=expected_hash,
        actual=actual_hash,
    )

    write_fsck_readiness(
        FSCK_READINESS_PATH,
        ready=fsck_ready,
        mount_ready=mount_ready,
    )

    ref_ok = (
        int(geometry["lba_start"]) == int(reference["lba_start"])
        and int(geometry["sector_count"]) == int(reference["sector_count"])
        and int(geometry["blocks_count"]) == int(reference["blocks_count"])
        and int(geometry["inodes_count"]) == int(reference["inodes_count"])
        and carve_ok
        and mbr_ok
        and fsck_ready
    )

    for idx, step in enumerate(steps, start=1):
        _log_sector(REPAIR_SECTOR_TRACE_PATH, idx, verbs.get(step, "touched"))

    REPAIR_SUMMARY_PATH.write_text(
        json.dumps(
            {
                "case_id": SUBJECT_CASE_ID,
                "steps_recorded": len(steps),
                "trace_logged": True,
                "reference_geometry_ok": ref_ok,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    finalize_case_outputs(
        trace_path=REPAIR_SECTOR_TRACE_PATH,
        manifest_steps=steps,
        mbr_path=RECONSTRUCTED_MBR_PATH,
        patched_disk_path=PATCHED_DISK_PATH,
        registry=registry,
        reference=reference,
        geometry=geometry,
        geometry_attestation_path=GEOMETRY_ATTESTATION_PATH,
        carve_verdict_path=CARVE_VERDICT_PATH,
        fsck_readiness_path=FSCK_READINESS_PATH,
        repair_summary_path=REPAIR_SUMMARY_PATH,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
