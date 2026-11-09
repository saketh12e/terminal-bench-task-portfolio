from __future__ import annotations

import hashlib
from typing import Any


def seal_findings_digest(findings: list[dict[str, Any]]) -> str:
    material = []
    for row in sorted(findings, key=lambda r: (r.get("file", ""), r.get("line", 0), r.get("rule_id", ""))):
        material.append(
            "|".join(
                [
                    str(row.get("rule_id", "")),
                    str(row.get("file", "")),
                    str(row.get("line", "")),
                    str(row.get("col", "")),
                    str(row.get("fingerprint", "")),
                    str(row.get("finding_stable", False)),
                ]
            )
        )
    return hashlib.sha256("\n".join(material).encode()).hexdigest()
