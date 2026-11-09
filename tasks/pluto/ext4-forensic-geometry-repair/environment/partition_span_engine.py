from __future__ import annotations


def solve_geometry(
    *,
    sector_size: int,
    anchor_lba: int,
    disk_size: int,
    registry: dict | None = None,
) -> dict:
    if registry is not None:
        anchor_lba = int(registry["primary_superblock_offset"]) // sector_size
    block_size = 1024
    lba_start = max(2048, anchor_lba)
    partition_bytes = disk_size - (lba_start * sector_size)
    blocks_count = partition_bytes // block_size
    inodes_count = blocks_count // 4
    return {
        "lba_start": lba_start,
        "sector_count": partition_bytes // sector_size,
        "block_size": block_size,
        "blocks_count": blocks_count,
        "inodes_count": inodes_count,
    }
