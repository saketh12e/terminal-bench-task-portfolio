from __future__ import annotations

import hashlib


def verify_carve_hash(disk: bytes, offset: int, length: int) -> str:
    span = disk[max(0, offset - 512) : max(0, offset - 512) + length]
    return hashlib.sha256(span).hexdigest()
