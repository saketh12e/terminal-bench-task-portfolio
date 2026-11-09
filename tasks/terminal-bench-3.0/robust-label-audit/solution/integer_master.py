"""Integer margin search with a restricted incumbent and a full-space dual bound."""

from types import SimpleNamespace
import numpy as np
from scipy.optimize import linprog, milp, Bounds, LinearConstraint
from scipy.sparse import csr_matrix, vstack


def margin_master(rows, rhs, buckets):
    original_count = rows.shape[1] - 1
    risk_mask = rows[:, -1] != 0
    groups = {}
    for j, values in enumerate(np.ascontiguousarray(rows[~risk_mask, :-1].T)):
        groups.setdefault(values.tobytes(), []).append(j)
    retained = []
    for members in groups.values():
        front = []
        for j in members:
            values = rows[risk_mask, j]
            if any(np.all(rows[risk_mask, i] <= values) for i in front):
                continue
            front = [i for i in front if not np.all(values <= rows[risk_mask, i])]
            front.append(j)
        retained.extend(front)
    retained = np.sort(retained)
    rows = rows[:, np.r_[retained, original_count]]
    k = rows.shape[1] - 1
    objective = np.r_[np.zeros(k), 1e6]
    risk = rows[:, -1] != 0
    low = float(rows[risk, :-1].min()) * buckets
    high = float(rows[risk, :-1].max()) * buckets
    eq = np.r_[np.ones(k), 0.0]
    lp = linprog(
        objective,
        A_ub=rows,
        b_ub=rhs,
        A_eq=eq[None, :],
        b_eq=[buckets],
        bounds=[(0, buckets)] * k + [(low, high)],
        method="highs",
        options={
            "primal_feasibility_tolerance": 1e-9,
            "dual_feasibility_tolerance": 1e-9,
        },
    )
    if not lp.success:
        raise RuntimeError(lp.message)

    def restricted(keep, seconds, caps=None):
        cols = np.r_[keep, k]
        scaled = rows[:, cols].copy()
        scaled[:, :-1] *= 1e6
        matrix = vstack(
            [
                csr_matrix(scaled),
                csr_matrix(eq[cols][None, :]),
            ],
            format="csr",
        )
        result = milp(
            np.r_[np.zeros(len(keep)), 1.0],
            integrality=np.r_[np.ones(len(keep)), 0.0],
            bounds=Bounds(
                np.r_[np.zeros(len(keep)), low * 1e6],
                np.r_[
                    np.full(len(keep), buckets) if caps is None else caps, high * 1e6
                ],
            ),
            constraints=LinearConstraint(
                matrix,
                np.r_[np.full(len(rows), -np.inf), buckets],
                np.r_[rhs * 1e6, buckets],
            ),
            options={"time_limit": seconds, "mip_rel_gap": 1e-7},
        )
        if result.x is not None:
            result.x[-1] /= 1e6
        return result

    order = np.argsort(lp.lower.marginals[:k])
    for size in (512, 2048, k):
        keep = np.sort(order[: min(size, k)])
        candidate = restricted(keep, 30.0)
        if candidate.x is not None:
            break
    if candidate.x is None:
        raise RuntimeError("integer finite relaxation has no incumbent")
    incumbent = candidate.fun
    # Lower-bound reduced cost is paid at least once by any used integer column.
    # Retain the bound for the removed region instead of pretending it does not exist.
    column_bounds = lp.fun + lp.lower.marginals[:k] - 1e-3
    keep = np.flatnonzero(column_bounds <= incumbent + 1e-3)
    costs = np.maximum(lp.lower.marginals[keep], 0.0)
    caps = np.minimum(
        buckets, np.floor((incumbent - lp.fun + 2e-3) / np.maximum(costs, 1e-20))
    )
    result = restricted(keep, 90.0, caps)
    if result.x is None:
        raise RuntimeError(result.message)
    removed = np.flatnonzero(column_bounds > incumbent + 1e-3)
    outside = float(column_bounds[removed].min()) if len(removed) else np.inf
    # Counts above these caps also cost more than the known incumbent.
    lower = min(float(result.mip_dual_bound), outside, incumbent)
    x = np.zeros(original_count + 1)
    x[retained[keep]] = result.x[:-1]
    x[-1] = result.x[-1]
    return SimpleNamespace(
        x=x, fun=result.fun, mip_dual_bound=lower, status=result.status
    )
