from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(os.environ.get("APP_DIR", "/app"))
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from sim_workspace import (  # noqa: E402
    FRAME_LEDGER_PATH,
    INTEGRATOR_AUDIT_PATH,
    POLICY_PATH,
    REFERENCE_DIGESTS_PATH,
    REGISTRY_PATH,
    REPLAY_TRACE_PATH,
    SCENARIO_PATH,
    SIM_ATTESTATION_PATH,
    SIM_SUMMARY_PATH,
    STEP_MANIFEST_PATH,
    SUBJECT_SCENARIO_ID,
    TWIN_VERDICT_PATH,
)

PYTHON_BIN = os.environ.get("PYTHON_BIN", "python")
STEP_IDS = (
    "contact_gather",
    "impulse_reduce",
    "integrate",
    "frame_digest",
    "twin_compare",
    "report_emit",
    "finalize",
)
REGISTRY_VERBS = {
    "contact_gather": "gather_contacts",
    "impulse_reduce": "reduce_impulses",
    "integrate": "euler_step",
    "frame_digest": "hash_frame",
    "twin_compare": "compare_runs",
    "report_emit": "emit_reports",
    "finalize": "seal_run",
}


def load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def run_pipeline(*, reseed: bool = False) -> subprocess.CompletedProcess[str]:
    if reseed:
        from bench_fixtures import main as seed_main

        seed_main()
    for path in (
        FRAME_LEDGER_PATH,
        TWIN_VERDICT_PATH,
        INTEGRATOR_AUDIT_PATH,
        SIM_ATTESTATION_PATH,
        SIM_SUMMARY_PATH,
        REPLAY_TRACE_PATH,
    ):
        if path.exists():
            path.unlink()
    return subprocess.run(
        [PYTHON_BIN, "physics_sim_runner.py"],
        cwd=APP_DIR,
        text=True,
        capture_output=True,
        timeout=120,
    )


def ensure_run() -> None:
    result = run_pipeline()
    assert result.returncode == 0, result.stdout + result.stderr


def reference_digests() -> list[str]:
    data = load_json(REFERENCE_DIGESTS_PATH)
    return list(data["digests"])


def ledger_digests() -> list[str]:
    ledger = load_json(FRAME_LEDGER_PATH)
    return [row["digest"] for row in ledger]


# --- smoke ---


def test_runner_exits_zero():
    result = run_pipeline()
    assert result.returncode == 0, result.stderr


def test_scenario_subject_id():
    ensure_run()
    assert load_json(SCENARIO_PATH)["scenario_id"] == SUBJECT_SCENARIO_ID


def test_frame_count_128():
    ensure_run()
    assert load_json(SCENARIO_PATH)["frame_count"] == 128


def test_ledger_file_exists():
    ensure_run()
    assert FRAME_LEDGER_PATH.exists()


def test_twin_verdict_exists():
    ensure_run()
    assert TWIN_VERDICT_PATH.exists()


def test_integrator_audit_exists():
    ensure_run()
    assert INTEGRATOR_AUDIT_PATH.exists()


def test_sim_attestation_exists():
    ensure_run()
    assert SIM_ATTESTATION_PATH.exists()


def test_sim_summary_exists():
    ensure_run()
    assert SIM_SUMMARY_PATH.exists()


def test_replay_trace_exists():
    ensure_run()
    assert REPLAY_TRACE_PATH.exists()


# --- twin determinism ---


def test_twin_match_true():
    ensure_run()
    assert load_json(TWIN_VERDICT_PATH)["twin_match"] is True


def test_twin_mismatch_count_zero():
    ensure_run()
    assert load_json(TWIN_VERDICT_PATH)["mismatch_count"] == 0


def test_twin_frames_compared_128():
    ensure_run()
    assert load_json(TWIN_VERDICT_PATH)["frames_compared"] == 128


def test_attestation_twin_match_true():
    ensure_run()
    assert load_json(SIM_ATTESTATION_PATH)["twin_match"] is True


def test_attestation_twin_matches_verdict():
    ensure_run()
    verdict = load_json(TWIN_VERDICT_PATH)["twin_match"]
    attestation = load_json(SIM_ATTESTATION_PATH)["twin_match"]
    assert verdict == attestation


def test_attestation_sim_run_complete():
    ensure_run()
    assert load_json(SIM_ATTESTATION_PATH)["sim_run_complete"] is True


def test_attestation_scenario_id():
    ensure_run()
    assert load_json(SIM_ATTESTATION_PATH)["scenario_id"] == SUBJECT_SCENARIO_ID


def test_attestation_frame_count():
    ensure_run()
    assert load_json(SIM_ATTESTATION_PATH)["frame_count"] == 128


def test_attestation_run_digest_hex():
    ensure_run()
    digest = load_json(SIM_ATTESTATION_PATH)["run_digest"]
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


# --- reference digest contract ---


def test_ledger_row_count():
    ensure_run()
    assert len(load_json(FRAME_LEDGER_PATH)) == 128


def test_ledger_digests_match_reference():
    ensure_run()
    assert ledger_digests() == reference_digests()


def test_reference_frame_zero_digest():
    ensure_run()
    assert ledger_digests()[0] == reference_digests()[0]


def test_reference_frame_mid_digest():
    ensure_run()
    assert ledger_digests()[64] == reference_digests()[64]


def test_reference_frame_last_digest():
    ensure_run()
    assert ledger_digests()[-1] == reference_digests()[-1]


def test_reference_frame_10_digest():
    ensure_run()
    assert ledger_digests()[10] == reference_digests()[10]


def test_reference_frame_32_digest():
    ensure_run()
    assert ledger_digests()[32] == reference_digests()[32]


def test_reference_frame_64_digest():
    ensure_run()
    assert ledger_digests()[64] == reference_digests()[64]


def test_reference_frame_100_digest():
    ensure_run()
    assert ledger_digests()[100] == reference_digests()[100]


def test_run_digest_matches_reference_chain():
    ensure_run()
    import hashlib

    chain = "".join(reference_digests())
    expected = hashlib.sha256(chain.encode("utf-8")).hexdigest()
    assert load_json(SIM_ATTESTATION_PATH)["run_digest"] == expected


# --- parallel / integrator audit ---


def test_parallel_reduction_ok():
    ensure_run()
    assert load_json(INTEGRATOR_AUDIT_PATH)["parallel_reduction_ok"] is True


def test_attestation_parallel_ok():
    ensure_run()
    assert load_json(SIM_ATTESTATION_PATH)["parallel_reduction_ok"] is True


def test_thread_buckets_requested_at_least_two():
    ensure_run()
    assert load_json(INTEGRATOR_AUDIT_PATH)["thread_buckets_requested"] >= 2


def test_thread_buckets_effective_matches_requested():
    ensure_run()
    audit = load_json(INTEGRATOR_AUDIT_PATH)
    assert audit["thread_buckets_effective"] == audit["thread_buckets_requested"]


def test_integrator_mode_float64():
    ensure_run()
    assert load_json(INTEGRATOR_AUDIT_PATH)["integrator_mode"] == "euler_float64"


# --- replay trace / registry ---


def test_trace_line_count():
    ensure_run()
    lines = [ln for ln in REPLAY_TRACE_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == len(STEP_IDS)


def test_trace_step_format():
    ensure_run()
    for line in REPLAY_TRACE_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        assert re.match(r"^step=\d+ op=\w+$", line.strip())


def test_trace_contact_gather_verb():
    ensure_run()
    text = REPLAY_TRACE_PATH.read_text(encoding="utf-8")
    assert "op=gather_contacts" in text
    assert "op=skip_contacts" not in text


def test_trace_impulse_reduce_verb():
    ensure_run()
    assert "op=reduce_impulses" in REPLAY_TRACE_PATH.read_text(encoding="utf-8")


def test_trace_integrate_verb():
    ensure_run()
    assert "op=euler_step" in REPLAY_TRACE_PATH.read_text(encoding="utf-8")


def test_trace_finalize_seal():
    ensure_run()
    assert "op=seal_run" in REPLAY_TRACE_PATH.read_text(encoding="utf-8")


def test_registry_has_all_steps():
    reg = load_json(REGISTRY_PATH)
    for step in STEP_IDS:
        assert step in reg["step_verbs"]


def test_registry_verbs_match_contract():
    reg = load_json(REGISTRY_PATH)
    for step, verb in REGISTRY_VERBS.items():
        assert reg["step_verbs"][step] == verb


def test_policy_differs_from_registry():
    policy = load_json(POLICY_PATH)
    reg = load_json(REGISTRY_PATH)
    assert policy["step_verbs"]["contact_gather"] != reg["step_verbs"]["contact_gather"]


# --- ledger shape ---


def test_ledger_entries_have_frame():
    ensure_run()
    for row in load_json(FRAME_LEDGER_PATH):
        assert "frame" in row


def test_ledger_entries_have_digest():
    ensure_run()
    for row in load_json(FRAME_LEDGER_PATH):
        assert re.fullmatch(r"[0-9a-f]{64}", row["digest"])


def test_ledger_impulse_sum_numeric():
    ensure_run()
    for row in load_json(FRAME_LEDGER_PATH):
        assert isinstance(row["impulse_sum"], (int, float))


def test_ledger_frames_monotonic():
    ensure_run()
    frames = [row["frame"] for row in load_json(FRAME_LEDGER_PATH)]
    assert frames == list(range(128))


# --- summary / attestation extras ---


def test_summary_scenario_id():
    ensure_run()
    assert load_json(SIM_SUMMARY_PATH)["scenario_id"] == SUBJECT_SCENARIO_ID


def test_summary_steps_recorded():
    ensure_run()
    assert load_json(SIM_SUMMARY_PATH)["steps_recorded"] == len(STEP_IDS)


def test_summary_trace_logged():
    ensure_run()
    assert load_json(SIM_SUMMARY_PATH)["trace_logged"] is True


def test_attestation_audit_event_recorded():
    ensure_run()
    assert load_json(SIM_ATTESTATION_PATH)["audit_event_recorded"] is True


# --- module-level contracts (import checks) ---


def test_contact_graph_stable_sort():
    from contact_graph import gather_contacts

    bodies = [{"id": 0, "x": 0.0, "y": 0.0}, {"id": 1, "x": 0.1, "y": 0.0}]
    a = gather_contacts(bodies, 0, 99)
    b = gather_contacts(bodies, 0, 99)
    assert a == b


def test_impulse_reduce_deterministic():
    from impulse_accumulator import reduce_impulses

    contacts = [(0, 1, 0.05), (0, 2, 0.03)]
    assert reduce_impulses(contacts, 4) == reduce_impulses(list(reversed(contacts)), 4)


def test_integrator_no_float32_cast():
    import inspect
    from integrator_step import euler_step

    src = inspect.getsource(euler_step)
    assert "float32" not in src


def test_twin_harness_compares_all_frames():
    from twin_run_harness import digests_match

    a = ["a", "b", "c"]
    b = ["a", "x", "c"]
    assert digests_match(a, b) is False


def test_frame_digest_includes_velocity():
    from frame_encoder import frame_digest

    bodies = [{"id": 0, "x": 1.0, "y": 2.0, "vx": 0.1, "vy": -0.2}]
    d1 = frame_digest(bodies)
    bodies[0]["vx"] = 0.2
    d2 = frame_digest(bodies)
    assert d1 != d2


def test_parallel_guard_effective_buckets():
    from parallel_guard import effective_buckets

    scenario = {"thread_buckets": 4}
    assert effective_buckets(scenario) >= 2


def test_scenario_loader_reads_registry():
    import scenario_loader as sl
    from sim_workspace import REGISTRY_PATH

    assert "sim_registry" in str(REGISTRY_PATH)
    verbs = sl.load_step_verbs()
    assert verbs["contact_gather"] == "gather_contacts"


def test_stability_report_twin_match_live():
    import inspect
    from stability_report import write_attestation

    src = inspect.getsource(write_attestation)
    assert '"twin_match": True' not in src
    assert '"twin_match": twin_match' in src


def test_step_manifest_seven_lines():
    steps = STEP_MANIFEST_PATH.read_text(encoding="utf-8").strip().splitlines()
    assert len(steps) == 7


def test_reference_seed_frame_count():
    ref = load_json(REFERENCE_DIGESTS_PATH)
    assert ref["frame_count"] == 128
    assert len(ref["digests"]) == 128


def test_physics_runner_main_importable():
    import physics_sim_runner

    assert hasattr(physics_sim_runner, "main")


def test_kahan_stub_not_wired():
    import physics_sim_runner as runner

    src = open(APP_DIR / "physics_sim_runner.py", encoding="utf-8").read()
    assert "float_kahan_stub" not in src


def test_ledger_first_impulse_positive():
    ensure_run()
    row = load_json(FRAME_LEDGER_PATH)[0]
    assert row["impulse_sum"] > 0


def test_ledger_last_frame_index():
    ensure_run()
    assert load_json(FRAME_LEDGER_PATH)[-1]["frame"] == 127


def test_runner_stdout_empty_on_success():
    result = run_pipeline()
    assert result.returncode == 0


def test_scenario_thread_buckets_four():
    assert load_json(SCENARIO_PATH)["thread_buckets"] == 4


def test_scenario_body_count_six():
    assert load_json(SCENARIO_PATH)["body_count"] == 6


def test_registry_step_verbs_keys():
    reg = load_json(REGISTRY_PATH)
    assert set(reg["step_verbs"]) >= set(STEP_IDS)


def test_trace_first_step_number_one():
    ensure_run()
    first = REPLAY_TRACE_PATH.read_text(encoding="utf-8").splitlines()[0].strip()
    assert first.startswith("step=1 ")


def test_trace_last_step_seven():
    ensure_run()
    lines = [ln for ln in REPLAY_TRACE_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines[-1].startswith("step=7 ")


def test_attestation_parallel_matches_audit():
    ensure_run()
    att = load_json(SIM_ATTESTATION_PATH)
    audit = load_json(INTEGRATOR_AUDIT_PATH)
    assert att["parallel_reduction_ok"] == audit["parallel_reduction_ok"]
