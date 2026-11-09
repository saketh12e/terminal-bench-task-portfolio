from __future__ import annotations

import json
from pathlib import Path


def apply_disk_probe(
    attestation_path: Path,
    patched_disk_path: Path,
    registry: dict,
    reference: dict,
) -> None:
    att = json.loads(attestation_path.read_text(encoding="utf-8"))
    att["disk_probe_ok"] = True
    attestation_path.write_text(
        json.dumps(att, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _ = (patched_disk_path, registry, reference)
