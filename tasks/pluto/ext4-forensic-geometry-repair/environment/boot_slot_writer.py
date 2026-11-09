from __future__ import annotations

import struct


def write_mbr_slot(mbr: bytearray, entry_offset: int, *, lba_start: int, sector_count: int, part_type: int) -> None:
    mbr[entry_offset + 4] = part_type & 0xFF
    struct.pack_into(">I", mbr, entry_offset + 8, lba_start)
    struct.pack_into(">I", mbr, entry_offset + 12, sector_count)
    mbr[510] = 0x55
    mbr[511] = 0xAA
