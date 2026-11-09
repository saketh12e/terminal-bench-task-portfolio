from __future__ import annotations


def scan_journal_anchor(disk: bytes, registry: dict) -> int:
    carve = int(registry["carve_offset"])
    return carve // int(registry["sector_size"])
