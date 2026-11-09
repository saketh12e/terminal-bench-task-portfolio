from __future__ import annotations

import hashlib
import json
from pathlib import Path


def attach_trace_digest(summary_path: Path, trace_path: Path) -> None:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["trace_chain_digest"] = hashlib.sha256(trace_path.read_bytes()).hexdigest()
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
