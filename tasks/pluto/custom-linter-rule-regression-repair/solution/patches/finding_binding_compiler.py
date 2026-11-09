from __future__ import annotations

import json
from typing import Any

from lint_scan_physics import finding_fingerprint
from lint_store_contract import FINDING_BINDING_POLICY_PATH


def bind_finding_row(hit: dict[str, Any]) -> dict[str, Any]:
    policy = json.loads(FINDING_BINDING_POLICY_PATH.read_text(encoding="utf-8"))
    fp = finding_fingerprint(hit["rule_id"], hit["file"], hit["line"], hit.get("col", 0), policy)
    return {
        "rule_id": hit["rule_id"],
        "file": hit["file"],
        "line": hit["line"],
        "col": hit.get("col", 0),
        "fingerprint": fp,
        "finding_stable": False,
    }
