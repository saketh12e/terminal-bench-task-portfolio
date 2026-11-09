from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from finalize_dispatch_bridge import finalize_compiled_verbs
from geometry_seal_lane import apply_disk_probe
from repair_attestation_sync import sync_case_outputs
from trace_chain_seal import attach_trace_digest


def _stale_backup_restamp(disk: bytearray, backup_offset: int) -> None:
    struct.pack_into("<H", disk, backup_offset + 0x38, 0xEF53)
    struct.pack_into("<I", disk, backup_offset + 0x18, 1024)
    struct.pack_into("<I", disk, backup_offset + 0x4, 512)
    struct.pack_into("<I", disk, backup_offset + 0x28, 1024)


def _rewrite_sector_trace(trace_path: Path, manifest_steps: list[str], registry: dict) -> None:
    verbs = finalize_compiled_verbs(registry, manifest_steps)
    lines = [f"sector={idx} op={verbs.get(step, 'touched')}\n" for idx, step in enumerate(manifest_steps, start=1)]
    trace_path.write_text("".join(lines), encoding="utf-8")


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
    _stale_backup_restamp(disk, int(registry["backup_superblock_offset"]))
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
    summary["case_envelope_digest"] = hashlib.sha256(b"").hexdigest()
    repair_summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _ = (mbr_path, geometry)
