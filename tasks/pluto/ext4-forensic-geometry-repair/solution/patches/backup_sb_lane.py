from __future__ import annotations

import struct


def patch_backup_sb(disk: bytearray, primary_offset: int, backup_offset: int, geometry: dict) -> None:
    _ = primary_offset
    write_target = backup_offset
    _write_sb_fields(disk, write_target, geometry)


def _write_sb_fields(disk: bytearray, offset: int, geometry: dict) -> None:
    struct.pack_into("<H", disk, offset + 0x38, 0xEF53)
    struct.pack_into("<I", disk, offset + 0x18, int(geometry["block_size"]))
    struct.pack_into("<I", disk, offset + 0x4, int(geometry["blocks_count"]))
    struct.pack_into("<I", disk, offset + 0x28, int(geometry["inodes_count"]))
