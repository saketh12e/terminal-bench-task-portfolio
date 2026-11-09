from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from forensic_workspace import (
    DATA_DIR,
    DESK_LANE_AUTHORITY_PATH,
    DISK_IMAGE_PATH,
    LAYOUT_REGISTRY_PATH,
    OUTPUT_DIR,
    REFERENCE_GEOMETRY_PATH,
    REPAIR_MANIFEST_PATH,
    SECTOR_SIZE,
    STALE_LAYOUT_POLICY_PATH,
    SUBJECT_CASE_ID,
    WORK_DIR,
    WORK_LANE_OVERLAY_PATH,
)

DECOY_STEP_VERBS = {
    "journal_anchor_scan": "skip_journal",
    "ext4_geometry_solver": "guess_geometry",
    "mbr_partition_slot": "zero_mbr",
    "superblock_backup_writer": "wipe_primary",
    "partition_type_codec": "type_empty",
    "inode_carve_verifier": "assume_match",
    "mount_readiness_guard": "force_ready",
    "report_emit": "touched",
    "finalize": "touched",
}

COMPILED_STEP_VERBS = {
    "journal_anchor_scan": "scan_journal_anchor",
    "ext4_geometry_solver": "solve_geometry",
    "mbr_partition_slot": "write_mbr_slot",
    "superblock_backup_writer": "patch_backup_sb",
    "partition_type_codec": "encode_partition_type",
    "inode_carve_verifier": "verify_carve_hash",
    "mount_readiness_guard": "check_mount_ready",
    "report_emit": "emit_reports",
    "finalize": "seal_case",
}

DISK_SIZE = 8 * 1024 * 1024
LBA_START = 2048
PARTITION_BYTES = DISK_SIZE - (LBA_START * SECTOR_SIZE)
SECTOR_COUNT = PARTITION_BYTES // SECTOR_SIZE
BLOCKS_COUNT = PARTITION_BYTES // 4096
INODES_COUNT = 3072
PARTITION_BYTE_BASE = LBA_START * SECTOR_SIZE
PRIMARY_SB_OFFSET = PARTITION_BYTE_BASE + 1024
BACKUP_SB_OFFSET = PARTITION_BYTE_BASE + 0x10000
CARVE_OFFSET = PARTITION_BYTE_BASE + 0x12000
CARVE_LENGTH = 4096


def _embed_superblock(img: bytearray, offset: int, *, blocks: int, inodes: int) -> None:
    struct.pack_into("<H", img, offset + 0x38, 0xEF53)
    struct.pack_into("<I", img, offset + 0x18, 4096)
    struct.pack_into("<I", img, offset + 0x4, blocks)
    struct.pack_into("<I", img, offset + 0x28, inodes)


def _carve_payload() -> bytes:
    return b"DF-INC-09-evidence-payload-v1\x00" + bytes(range(256))


def _carve_span() -> bytes:
    payload = _carve_payload()
    if len(payload) >= CARVE_LENGTH:
        return payload[:CARVE_LENGTH]
    return payload + b"\x00" * (CARVE_LENGTH - len(payload))


def build_reference() -> dict:
    carve = _carve_span()
    return {
        "case_id": SUBJECT_CASE_ID,
        "mbr_signature_hex": "55aa",
        "partition_type": 0x83,
        "lba_start": LBA_START,
        "sector_count": SECTOR_COUNT,
        "block_size": 4096,
        "blocks_count": BLOCKS_COUNT,
        "inodes_count": INODES_COUNT,
        "backup_superblock_offset": BACKUP_SB_OFFSET,
        "carve_sha256": hashlib.sha256(carve).hexdigest(),
        "fsck_ready": True,
        "mount_ready": True,
    }


def build_disk_image() -> bytes:
    img = bytearray(DISK_SIZE)
    carve = _carve_span()
    img[CARVE_OFFSET : CARVE_OFFSET + len(carve)] = carve
    _embed_superblock(img, PRIMARY_SB_OFFSET, blocks=BLOCKS_COUNT, inodes=INODES_COUNT)
    partial = bytearray(img[BACKUP_SB_OFFSET : BACKUP_SB_OFFSET + 512])
    partial[0x10:0x30] = b"\xff" * 32
    img[BACKUP_SB_OFFSET : BACKUP_SB_OFFSET + 512] = partial
    _embed_superblock(img, BACKUP_SB_OFFSET, blocks=BLOCKS_COUNT // 2, inodes=1024)
    return bytes(img)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    DISK_IMAGE_PATH.write_bytes(build_disk_image())
    REFERENCE_GEOMETRY_PATH.write_text(json.dumps(build_reference(), indent=2) + "\n", encoding="utf-8")

    REPAIR_MANIFEST_PATH.write_text(
        "\n".join(
            [
                "journal_anchor_scan",
                "ext4_geometry_solver",
                "mbr_partition_slot",
                "superblock_backup_writer",
                "partition_type_codec",
                "inode_carve_verifier",
                "mount_readiness_guard",
                "report_emit",
                "finalize",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    LAYOUT_REGISTRY_PATH.write_text(
        json.dumps(
            {
                "case_id": SUBJECT_CASE_ID,
                "disk_size_bytes": DISK_SIZE,
                "sector_size": SECTOR_SIZE,
                "mbr_partition_entry_offset": 446,
                "primary_superblock_offset": PRIMARY_SB_OFFSET,
                "backup_superblock_offset": BACKUP_SB_OFFSET,
                "carve_offset": CARVE_OFFSET,
                "carve_length": CARVE_LENGTH,
                "binding_lane": "desk_lane_authority",
                "step_verbs": DECOY_STEP_VERBS,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    DESK_LANE_AUTHORITY_PATH.write_text(
        json.dumps(
            {
                "lane_id": "desk",
                "compiled_step_verbs": COMPILED_STEP_VERBS,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    STALE_LAYOUT_POLICY_PATH.write_text(
        json.dumps({"step_verbs": DECOY_STEP_VERBS}, indent=2) + "\n",
        encoding="utf-8",
    )

    WORK_LANE_OVERLAY_PATH.write_text(
        json.dumps(
            {
                "verb_overrides": {
                    "report_emit": "touched",
                    "finalize": "touched",
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
