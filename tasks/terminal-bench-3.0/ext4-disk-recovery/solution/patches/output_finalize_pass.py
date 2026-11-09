from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backup_sb_lane import patch_backup_sb
from finalize_dispatch_bridge import finalize_compiled_verbs
from geometry_seal_lane import apply_disk_probe
from repair_attestation_sync import sync_case_outputs
from trace_chain_seal import attach_trace_digest


def _rewrite_sector_trace(trace_path: Path, manifest_steps: list[str], registry: dict) -> None:
    verbs = finalize_compiled_verbs(registry, manifest_steps)
    lines = [f"sector={idx} op={verbs.get(step, 'touched')}\n" for idx, step in enumerate(manifest_steps, start=1)]
    trace_path.write_text("".join(lines), encoding="utf-8")


def _case_envelope_digest(
    mbr_path: Path,
    trace_path: Path,
    patched_disk_path: Path,
    registry: dict,
) -> str:
    mbr = mbr_path.read_bytes()
    trace = trace_path.read_bytes()
    off = int(registry["carve_offset"])
    ln = int(registry["carve_length"])
    carve = patched_disk_path.read_bytes()[off : off + ln]
    return hashlib.sha256(mbr + trace + carve).hexdigest()


def finalize_case_outputs(
    *,
    trace_path: Path,
    manifest_steps: list[str],
    mbr_path: Path,
    patched_disk_path: Path,
    registry: dict,
    reference: dict,
    geometry: dict,
    geometry_attestation_path: Path,
    carve_verdict_path: Path,
    fsck_readiness_path: Path,
    repair_summary_path: Path,
) -> None:
    disk = bytearray(patched_disk_path.read_bytes())
    patch_backup_sb(
        disk,
        int(registry["primary_superblock_offset"]),
        int(registry["backup_superblock_offset"]),
        geometry,
    )
    patched_disk_path.write_bytes(disk)

    sync_case_outputs(
        patched_disk_path=patched_disk_path,
        registry=registry,
        reference=reference,
        geometry_attestation_path=geometry_attestation_path,
        carve_verdict_path=carve_verdict_path,
        fsck_readiness_path=fsck_readiness_path,
        repair_summary_path=repair_summary_path,
    )
    _rewrite_sector_trace(trace_path, manifest_steps, registry)
    apply_disk_probe(
        geometry_attestation_path,
        patched_disk_path,
        registry,
        reference,
    )
    attach_trace_digest(repair_summary_path, trace_path)
    summary = json.loads(repair_summary_path.read_text(encoding="utf-8"))
    summary["case_envelope_digest"] = _case_envelope_digest(
        mbr_path, trace_path, patched_disk_path, registry
    )
    repair_summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
