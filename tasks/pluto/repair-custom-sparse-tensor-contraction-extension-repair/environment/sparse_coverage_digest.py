from __future__ import annotations

import hashlib
import json
from typing import Any


def weak_digest(rows: list[dict[str, Any]]) -> str:
    material = json.dumps([r.get("pattern_id") for r in rows], sort_keys=True)
    return hashlib.sha256(material.encode()).hexdigest()[:16]
