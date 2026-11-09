from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_scan_report(
    path: Path,
    *,
    case_id: str,
    findings: list[dict[str, Any]],
    scan_verified: bool,
    corpus_aligned: bool,
) -> None:
    doc = {
        "case_id": case_id,
        "finding_count": len(findings),
        "findings": findings,
        "scan_verified": scan_verified,
        "corpus_aligned": corpus_aligned,
        "scan_complete": False,
    }
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
