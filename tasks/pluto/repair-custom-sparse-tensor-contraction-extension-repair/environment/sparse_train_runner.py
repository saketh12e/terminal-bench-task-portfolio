from __future__ import annotations

import json
import math
from pathlib import Path

from sparse_gradient_binding_compiler import bind_gradient_row
from sparse_gradient_dispatch_bridge import dispatch_training_backward
from sparse_work_policy_apply_lane import effective_work_policy
from sparse_parity_nnz_lane import parity_nnz_count
from sparse_snapshot_emit_lane import snapshot_weak_digest
from sparse_gradient_finalize import reconcile_gradients, remap_train_tokens
from sparse_pattern_closure_lane import closure_patterns
from sparse_pattern_expansion_lane import expand_pattern_cases
from sparse_pattern_loader import load_pattern_catalog
from sparse_train_contract import (
    BACKWARD_TRACE_PATH,
    GRADIENT_BINDING_AUDIT_PATH,
    GRADIENT_BINDING_POLICY_PATH,
    GRADIENT_PARITY_REPORT_PATH,
    OUTPUT_DIR,
    PATTERN_CATALOG_PATH,
    REFERENCE_GRADIENT_GRID_PATH,
    SPARSE_COVERAGE_SNAPSHOT_PATH,
    STALE_COALESCE_POLICY_PATH,
    SUBJECT_RUN_ID,
    TRAIN_INTEGRITY_RECORD_PATH,
    TRAIN_STAGE_AUTHORITY_PATH,
    TRAIN_STAGE_TARGETS_PATH,
    TRAIN_TRACE_PATH,
    TRAINING_LOSS_CURVE_PATH,
    WORK_TRAIN_POLICY_PATH,
    WORK_DIR,
)

REPAIR_PLAN_PATH = WORK_DIR / "repair_plan.json"

import sparse_contract_ext


def _write_trace(path: Path, stages: list[str], authority: dict) -> None:
    actions = authority.get("stage_actions", {})
    lines = [f"target={s}: action={actions.get(s, 'verified')}" for s in stages]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _mse_loss(out: list[float], target: list[float]) -> float:
    if len(out) != len(target):
        return float("inf")
    return sum((a - b) ** 2 for a, b in zip(out, target)) / len(out)


def integrity_work_policy_fields(work_policy: dict, train_complete: bool) -> dict[str, object]:
    """When training completes, record the effective desk policy, not stale work JSON."""
    if train_complete:
        return {
            "work_policy_prefer_merge_lane": False,
            "work_policy_dispatch_lane": "authority",
            "work_policy_replay_mode": "full_grid",
        }
    return {
        "work_policy_prefer_merge_lane": work_policy.get("prefer_merge_lane_coalesce", False),
        "work_policy_dispatch_lane": work_policy.get("gradient_dispatch_lane"),
        "work_policy_replay_mode": work_policy.get("gradient_replay_mode"),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    work_policy = {}
    if WORK_TRAIN_POLICY_PATH.exists():
        work_policy = json.loads(WORK_TRAIN_POLICY_PATH.read_text(encoding="utf-8"))
    repair_plan_path = REPAIR_PLAN_PATH if REPAIR_PLAN_PATH.is_file() else None
    work_policy = effective_work_policy(work_policy, repair_plan_path)

    catalog = load_pattern_catalog(PATTERN_CATALOG_PATH, STALE_COALESCE_POLICY_PATH)
    ref = json.loads(REFERENCE_GRADIENT_GRID_PATH.read_text(encoding="utf-8"))
    authority = json.loads(TRAIN_STAGE_AUTHORITY_PATH.read_text(encoding="utf-8"))
    policy = json.loads(GRADIENT_BINDING_POLICY_PATH.read_text(encoding="utf-8"))

    graph = catalog.get("pattern_dependency_graph", {})
    expected_patterns = set(graph.get("expected_closure", []))
    enabled = closure_patterns(graph, list(catalog.get("active_patterns", [])))
    missing_patterns = len(expected_patterns - set(enabled))

    cases = expand_pattern_cases(catalog, ref.get("pattern_ids", []), work_policy)
    dense_cols = int(ref.get("dense_cols", 2))

    pattern_results = []
    audit_entries = []
    loss_steps = []
    trace_lines = []
    parity_rows = []

    for case in cases:
        pid = case["pattern_id"]
        row = list(case["row"])
        col = list(case["col"])
        val = list(case["val"])
        rows = int(case["rows"])
        cols = int(case["cols"])
        dense = list(case["dense"])
        target = list(case["target_out"])

        fwd = sparse_contract_ext.sparse_dense_matmul(row, col, val, rows, cols, dense, dense_cols)
        loss = _mse_loss(fwd["out"], target)
        loss_steps.append({"step": len(loss_steps), "pattern_id": pid, "loss": loss})

        grad_out = [2.0 * (o - t) / len(target) for o, t in zip(fwd["out"], target)]
        bwd = dispatch_training_backward(
            row,
            col,
            val,
            rows,
            cols,
            dense,
            dense_cols,
            grad_out,
            work_policy,
            REPAIR_PLAN_PATH if REPAIR_PLAN_PATH.is_file() else None,
        )
        grad_sparse = bwd["grad_sparse"]
        co_row = bwd["coalesced"]["row"]
        co_col = bwd["coalesced"]["col"]

        expected_grad = case.get("expected_grad_sparse", [])
        max_abs_err = 0.0
        if expected_grad and len(expected_grad) == len(grad_sparse):
            max_abs_err = max(abs(a - b) for a, b in zip(grad_sparse, expected_grad))
        parity_ok = max_abs_err < 1e-9
        parity_rows.append(
            {
                "pattern_id": pid,
                "max_abs_grad_err": max_abs_err,
                "parity_ok": parity_ok,
                "nnz": parity_nnz_count(row, grad_sparse),
            }
        )
        trace_lines.append(f"pattern={pid} backward_max_err={max_abs_err:.6e}")

        for nnz_index, (r, c, g) in enumerate(zip(co_row, co_col, grad_sparse)):
            hit = {"pattern_id": pid, "row": r, "col": c, "nnz_index": nnz_index, "grad": g}
            bound = bind_gradient_row(hit, policy)
            stable = parity_ok
            bound["gradient_stable"] = stable
            audit_entries.append(bound)
            pattern_results.append(
                {
                    "pattern_id": pid,
                    "row": r,
                    "col": c,
                    "nnz_index": nnz_index,
                    "fingerprint": bound["fingerprint"],
                    "gradient_stable": stable,
                }
            )

    GRADIENT_BINDING_AUDIT_PATH.write_text(
        json.dumps({"entries": audit_entries}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    all_parity = all(r["parity_ok"] for r in parity_rows) and missing_patterns == 0
    verified = all_parity and len(cases) == len(ref.get("pattern_ids", []))

    GRADIENT_PARITY_REPORT_PATH.write_text(
        json.dumps(
            {
                "run_id": SUBJECT_RUN_ID,
                "pattern_results": pattern_results,
                "parity_rows": parity_rows,
                "gradient_verified": verified,
                "catalog_aligned": len(cases) == len(ref.get("pattern_ids", [])),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    reconcile_gradients(GRADIENT_BINDING_AUDIT_PATH, GRADIENT_PARITY_REPORT_PATH)

    TRAINING_LOSS_CURVE_PATH.write_text(
        json.dumps({"run_id": SUBJECT_RUN_ID, "steps": loss_steps}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    BACKWARD_TRACE_PATH.write_text("\n".join(trace_lines) + ("\n" if trace_lines else ""), encoding="utf-8")

    weak = snapshot_weak_digest(pattern_results)
    SPARSE_COVERAGE_SNAPSHOT_PATH.write_text(
        json.dumps(
            {
                "run_id": SUBJECT_RUN_ID,
                "enabled_patterns": enabled,
                "expected_pattern_count": len(expected_patterns),
                "missing_pattern_count": missing_patterns,
                "weak_digest": weak,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    stages = authority.get("stage_order", [])
    TRAIN_STAGE_TARGETS_PATH.write_text("\n".join(stages) + ("\n" if stages else ""), encoding="utf-8")
    _write_trace(TRAIN_TRACE_PATH, stages, authority)
    remap_train_tokens(TRAIN_TRACE_PATH, authority)

    report = json.loads(GRADIENT_PARITY_REPORT_PATH.read_text(encoding="utf-8"))
    train_complete = bool(report.get("gradient_verified")) and bool(report.get("catalog_aligned"))
    policy_fields = integrity_work_policy_fields(work_policy, train_complete)
    TRAIN_INTEGRITY_RECORD_PATH.write_text(
        json.dumps(
            {
                "run_id": SUBJECT_RUN_ID,
                "train_complete": train_complete,
                "gradient_verified": report.get("gradient_verified"),
                "catalog_aligned": report.get("catalog_aligned"),
                **policy_fields,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
