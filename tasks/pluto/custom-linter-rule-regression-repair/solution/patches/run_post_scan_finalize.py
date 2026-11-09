from __future__ import annotations

import json
from pathlib import Path

from lint_store_contract import SCAN_STAGE_AUTHORITY_PATH


def reconcile_findings(audit_path: Path, report_path: Path) -> None:
    return


def overlay_scan_flags(report_path: Path, integrity_path: Path) -> None:
    return


def remap_scan_tokens(log_path: Path) -> None:
    if not log_path.exists() or not SCAN_STAGE_AUTHORITY_PATH.exists():
        return
    authority = json.loads(SCAN_STAGE_AUTHORITY_PATH.read_text(encoding="utf-8"))
    actions = authority.get("stage_actions", {})
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    rebuilt = []
    for line in lines:
        if ": action=" not in line:
            rebuilt.append(line)
            continue
        stage = line.split("target=", 1)[1].split(":", 1)[0].strip()
        token = actions.get(stage, "touched")
        rebuilt.append(f"target={stage}: action={token}")
    log_path.write_text("\n".join(rebuilt) + ("\n" if rebuilt else ""), encoding="utf-8")
