from __future__ import annotations

import hashlib


def verify_carve_hash(disk: bytes, offset: int, length: int) -> str:
    return hashlib.sha256(disk[offset : offset + length]).hexdigest()
