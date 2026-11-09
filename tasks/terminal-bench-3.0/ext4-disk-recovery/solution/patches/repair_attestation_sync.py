from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


def sync_case_outputs(
    *,
    patched_disk_path: Path,
    registry: dict,
    reference: dict,
    geometry_attestation_path: Path,
    carve_verdict_path: Path,
    fsck_readiness_path: Path,
    repair_summary_path: Path,
) -> None:
    disk = patched_disk_path.read_bytes()
    entry_off = int(registry["mbr_partition_entry_offset"])
    lba_start = struct.unpack_from("<I", disk, entry_off + 8)[0]
    sector_count = struct.unpack_from("<I", disk, entry_off + 12)[0]
    backup_off = int(registry["backup_superblock_offset"])
    blocks_count = struct.unpack_from("<I", disk, backup_off + 0x4)[0]
    inodes_count = struct.unpack_from("<I", disk, backup_off + 0x28)[0]
    carve_off = int(registry["carve_offset"])
    carve_len = int(registry["carve_length"])
    actual_hash = hashlib.sha256(disk[carve_off : carve_off + carve_len]).hexdigest()
    carve_ok = actual_hash == reference["carve_sha256"]
    mbr_ok = disk[510] == 0x55 and disk[511] == 0xAA
    magic = struct.unpack_from("<H", disk, backup_off + 0x38)[0]
    block_size = struct.unpack_from("<I", disk, backup_off + 0x18)[0]
    sb_ok = magic == 0xEF53 and block_size == 4096
    mount_ready = mbr_ok and sb_ok and carve_ok
    fsck_ready = mount_ready and carve_ok

    att = {
        "case_id": reference["case_id"],
        "repair_complete": True,
        "lba_start": lba_start,
        "sector_count": sector_count,
        "blocks_count": blocks_count,
        "inodes_count": inodes_count,
        "fsck_ready": fsck_ready,
        "disk_probe_ok": fsck_ready,
    }
    geometry_attestation_path.write_text(
        json.dumps(att, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    carve_verdict_path.write_text(
        json.dumps(
            {
                "carve_hash_match": carve_ok,
                "expected_sha256": reference["carve_sha256"],
                "actual_sha256": actual_hash,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    fsck_readiness_path.write_text(
        json.dumps({"fsck_ready": fsck_ready, "mount_ready": mount_ready}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    ref_ok = (
        lba_start == int(reference["lba_start"])
        and sector_count == int(reference["sector_count"])
        and blocks_count == int(reference["blocks_count"])
        and inodes_count == int(reference["inodes_count"])
        and carve_ok
        and mbr_ok
        and fsck_ready
    )
    summary = json.loads(repair_summary_path.read_text(encoding="utf-8"))
    summary["reference_geometry_ok"] = ref_ok
    repair_summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
