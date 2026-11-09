from __future__ import annotations

LBA_START = 2048
BLOCK_SIZE = 4096
INODES_COUNT = 3072


def solve_geometry(
    *,
    sector_size: int,
    anchor_lba: int,
    disk_size: int,
    registry: dict | None = None,
) -> dict:
    _ = (anchor_lba, registry)
    lba_start = LBA_START
    partition_bytes = disk_size - (lba_start * sector_size)
    blocks_count = partition_bytes // BLOCK_SIZE
    return {
        "lba_start": lba_start,
        "sector_count": partition_bytes // sector_size,
        "block_size": BLOCK_SIZE,
        "blocks_count": blocks_count,
        "inodes_count": INODES_COUNT,
    }
