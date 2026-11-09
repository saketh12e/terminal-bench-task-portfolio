from __future__ import annotations

import hashlib
import json
from typing import Any

from lint_store_contract import FINDING_BINDING_POLICY_PATH


def bind_finding_row(hit: dict[str, Any]) -> dict[str, Any]:
    policy = json.loads(FINDING_BINDING_POLICY_PATH.read_text(encoding="utf-8"))
    material = "|".join([hit["file"], str(hit["line"])])
    fp = hashlib.sha256(material.encode()).hexdigest()[: int(policy["digest_hex_length"])]
    return {
        "rule_id": hit["rule_id"],
        "file": hit["file"],
        "line": hit["line"],
        "col": hit.get("col", 0),
        "fingerprint": fp,
        "finding_stable": False,
    }
