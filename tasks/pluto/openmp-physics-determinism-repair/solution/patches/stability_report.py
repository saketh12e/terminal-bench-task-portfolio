from __future__ import annotations

import json
from pathlib import Path


def write_twin_verdict(path: Path, *, match: bool, frames: int, mismatches: int) -> dict:
    payload = {
        "twin_match": match,
        "frames_compared": frames,
        "mismatch_count": mismatches,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_attestation(
    path: Path,
    *,
    scenario_id: str,
    frame_count: int,
    twin_match: bool,
    parallel_ok: bool,
    run_digest: str,
) -> dict:
    payload = {
        "scenario_id": scenario_id,
        "sim_run_complete": True,
        "frame_count": frame_count,
        "twin_match": twin_match,
        "parallel_reduction_ok": parallel_ok,
        "run_digest": run_digest,
        "audit_event_recorded": True,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_summary(path: Path, *, scenario_id: str, steps_recorded: int) -> dict:
    payload = {
        "scenario_id": scenario_id,
        "steps_recorded": steps_recorded,
        "trace_logged": True,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload
