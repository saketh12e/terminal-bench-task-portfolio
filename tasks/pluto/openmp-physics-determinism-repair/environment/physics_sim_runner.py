from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

from contact_graph import gather_contacts
from frame_encoder import frame_digest, ledger_entry
from impulse_accumulator import reduce_impulses
from integrator_step import euler_step
from parallel_guard import effective_buckets, parallel_ok, thread_buckets_requested
from scenario_loader import resolve_step_verbs
from sim_workspace import (
    FRAME_LEDGER_PATH,
    INTEGRATOR_AUDIT_PATH,
    OUTPUT_DIR,
    REFERENCE_DIGESTS_PATH,
    REPLAY_TRACE_PATH,
    SCENARIO_PATH,
    SIM_ATTESTATION_PATH,
    SIM_SUMMARY_PATH,
    STEP_MANIFEST_PATH,
    TWIN_VERDICT_PATH,
    WORK_DIR,
)
from stability_report import write_attestation, write_summary, write_twin_verdict
from twin_run_harness import digests_match


def _init_bodies(count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    bodies = []
    for i in range(count):
        bodies.append(
            {
                "id": i,
                "x": rng.uniform(-5.0, 5.0),
                "y": rng.uniform(-5.0, 5.0),
                "vx": rng.uniform(-0.5, 0.5),
                "vy": rng.uniform(-0.5, 0.5),
            }
        )
    return bodies


def _clone_bodies(bodies: list[dict]) -> list[dict]:
    return [dict(b) for b in bodies]


def _simulate_frame(
    bodies: list[dict],
    frame_idx: int,
    seed: int,
    thread_buckets: int,
) -> tuple[str, float]:
    contacts = gather_contacts(bodies, frame_idx, seed)
    impulse_sum = reduce_impulses(contacts, thread_buckets)
    euler_step(bodies, impulse_sum)
    digest = frame_digest(bodies)
    return digest, impulse_sum


def _run_once(scenario: dict, *, seed_offset: int = 0) -> tuple[list[str], list[dict]]:
    seed = int(scenario["seed"]) + seed_offset
    frame_count = int(scenario["frame_count"])
    bodies = _init_bodies(int(scenario["body_count"]), seed)
    buckets = effective_buckets(scenario)
    digests: list[str] = []
    ledger: list[dict] = []
    for frame_idx in range(frame_count):
        digest, impulse_sum = _simulate_frame(bodies, frame_idx, seed, buckets)
        digests.append(digest)
        ledger.append(ledger_entry(frame_idx, digest, impulse_sum))
    return digests, ledger


def _log_step(trace_path: Path, step_id: int, verb: str) -> None:
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("a", encoding="utf-8") as fh:
        fh.write(f"step={step_id} op={verb}\n")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    steps = STEP_MANIFEST_PATH.read_text(encoding="utf-8").strip().splitlines()
    verbs = resolve_step_verbs(steps)

    trace_path = REPLAY_TRACE_PATH
    if trace_path.exists():
        trace_path.unlink()

    run_a, ledger_a = _run_once(scenario, seed_offset=0)
    run_b, _ledger_b = _run_once(scenario, seed_offset=1)

    twin_match = digests_match(run_a, run_b)
    mismatch_count = sum(1 for a, b in zip(run_a, run_b) if a != b)

    ref_payload = json.loads(REFERENCE_DIGESTS_PATH.read_text(encoding="utf-8"))
    ledger_digests = [row["digest"] for row in ledger_a]
    reference_ok = ledger_digests == ref_payload["digests"]
    if not reference_ok:
        twin_match = False

    FRAME_LEDGER_PATH.write_text(json.dumps(ledger_a, indent=2) + "\n", encoding="utf-8")

    audit = {
        "integrator_mode": "euler_float32",
        "thread_buckets_requested": thread_buckets_requested(scenario),
        "thread_buckets_effective": effective_buckets(scenario),
        "parallel_reduction_ok": parallel_ok(scenario),
    }
    INTEGRATOR_AUDIT_PATH.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    write_twin_verdict(
        TWIN_VERDICT_PATH,
        match=twin_match,
        frames=len(run_a),
        mismatches=mismatch_count,
    )

    run_digest = hashlib.sha256("".join(run_a).encode("utf-8")).hexdigest()
    write_attestation(
        SIM_ATTESTATION_PATH,
        scenario_id=scenario["scenario_id"],
        frame_count=len(run_a),
        twin_match=twin_match,
        parallel_ok=parallel_ok(scenario),
        run_digest=run_digest,
    )

    for idx, step in enumerate(steps, start=1):
        _log_step(trace_path, idx, verbs.get(step, "touched"))

    write_summary(
        SIM_SUMMARY_PATH,
        scenario_id=scenario["scenario_id"],
        steps_recorded=len(steps),
    )

    _ = reference_ok
    return 0


if __name__ == "__main__":
    sys.exit(main())
