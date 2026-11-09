from __future__ import annotations


def check_mount_ready(*, mbr_ok: bool, sb_ok: bool, carve_ok: bool) -> bool:
    return bool(mbr_ok and sb_ok and carve_ok)
