from __future__ import annotations

import hashlib
from typing import Any


def weak_digest(findings: list[dict[str, Any]]) -> str:
    files = sorted({str(r.get("file", "")) for r in findings})
    return hashlib.sha256("|".join(files).encode()).hexdigest()


def rule_graph_digest(findings: list[dict[str, Any]]) -> str:
    from integrity_digest_seal import seal_findings_digest

    return seal_findings_digest(findings)
