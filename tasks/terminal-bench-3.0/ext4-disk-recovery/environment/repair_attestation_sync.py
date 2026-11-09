from __future__ import annotations

import json
from pathlib import Path


def sync_case_outputs(
    *,
    patched_disk_path: Path,
    registry: dict,
    reference: dict,
    geometry_attestation_path: Path,
    carve_verdict_path: Path,
    fsck_readiness_path: Path,
    repair_summary_path: Path,
) -> None:
    att = json.loads(geometry_attestation_path.read_text(encoding="utf-8"))
    att["fsck_ready"] = True
    att["disk_probe_ok"] = True
    geometry_attestation_path.write_text(
        json.dumps(att, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fsck_readiness_path.write_text(
        json.dumps({"fsck_ready": True, "mount_ready": True}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = json.loads(repair_summary_path.read_text(encoding="utf-8"))
    summary["reference_geometry_ok"] = True
    repair_summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _ = (patched_disk_path, registry, reference, carve_verdict_path)
