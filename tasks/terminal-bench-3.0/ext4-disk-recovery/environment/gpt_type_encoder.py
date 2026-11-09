from __future__ import annotations


def encode_partition_type(linux: bool = True) -> int:
    if linux:
        return 0x00
    return 0x83
