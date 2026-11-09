from __future__ import annotations


def scan_journal_anchor(disk: bytes, registry: dict) -> int:
    return int(registry["primary_superblock_offset"]) // registry["sector_size"]
