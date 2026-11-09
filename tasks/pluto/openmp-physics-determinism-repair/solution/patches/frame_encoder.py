from __future__ import annotations

import hashlib
import json
from typing import Any


def frame_digest(bodies: list[dict[str, Any]]) -> str:
    canonical = json.dumps(sorted(bodies, key=lambda b: b["id"]), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ledger_entry(frame_idx: int, digest: str, impulse_sum: float) -> dict[str, Any]:
    return {
        "frame": frame_idx,
        "digest": digest,
        "impulse_sum": round(impulse_sum, 8),
    }
