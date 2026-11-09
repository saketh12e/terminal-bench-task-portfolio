from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


def _live_probe_ok(disk: bytes, registry: dict, reference: dict) -> bool:
    entry_off = int(registry["mbr_partition_entry_offset"])
    lba_start = struct.unpack_from("<I", disk, entry_off + 8)[0]
    sector_count = struct.unpack_from("<I", disk, entry_off + 12)[0]
    backup_off = int(registry["backup_superblock_offset"])
    blocks_count = struct.unpack_from("<I", disk, backup_off + 0x4)[0]
    inodes_count = struct.unpack_from("<I", disk, backup_off + 0x28)[0]
    carve_off = int(registry["carve_offset"])
    carve_len = int(registry["carve_length"])
    carve_ok = hashlib.sha256(disk[carve_off : carve_off + carve_len]).hexdigest() == reference["carve_sha256"]
    mbr_ok = disk[510] == 0x55 and disk[511] == 0xAA
    magic = struct.unpack_from("<H", disk, backup_off + 0x38)[0]
    block_size = struct.unpack_from("<I", disk, backup_off + 0x18)[0]
    sb_ok = magic == 0xEF53 and block_size == 4096
    mount_ready = mbr_ok and sb_ok and carve_ok
    fsck_ready = mount_ready and carve_ok
    return (
        lba_start == int(reference["lba_start"])
        and sector_count == int(reference["sector_count"])
        and blocks_count == int(reference["blocks_count"])
        and inodes_count == int(reference["inodes_count"])
        and carve_ok
        and mbr_ok
        and fsck_ready
    )


def apply_disk_probe(
    attestation_path: Path,
    patched_disk_path: Path,
    registry: dict,
    reference: dict,
) -> None:
    disk = patched_disk_path.read_bytes()
    att = json.loads(attestation_path.read_text(encoding="utf-8"))
    att["disk_probe_ok"] = _live_probe_ok(disk, registry, reference)
    attestation_path.write_text(
        json.dumps(att, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
