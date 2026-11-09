"""Certify a global lower bound using a finite relaxation over all deployable trees."""

import numpy as np
from scipy import sparse
from scipy.optimize import linprog, milp, Bounds, LinearConstraint
from planner_evaluator import FEAS_TOL, GATE_EPS, coefficients
from calibration import SAMPLES


def integer_margin_bound(matrix, rhs, buckets, regret_rows):
    """Bound all allocations, including those excluded by dual reduced-cost fixing."""
    # Within identical safety/floor columns, replacing a tree by a componentwise
    # better risk column preserves integral counts and every finite-bank rule.
    # This is exact coefficient dominance, with no approximate comparisons.
    grouped = {}
    for j, column in enumerate(np.ascontiguousarray(matrix[regret_rows:, :-1].T)):
        grouped.setdefault(column.tobytes(), []).append(j)
    frontier = []
    for members in grouped.values():
        risks = matrix[:regret_rows, members].T
        order = np.lexsort(tuple(risks[:, i] for i in reversed(range(regret_rows))))
        retained = []
        for index in order:
            if retained and np.any(np.all(risks[retained] <= risks[index], axis=1)):
                continue
            retained.append(index)
        frontier.extend(members[i] for i in retained)
    matrix = matrix[:, np.r_[np.sort(frontier), matrix.shape[1] - 1]]
    n = matrix.shape[1] - 1
    objective = np.r_[np.zeros(n), 1e6]
    low = float(matrix[:regret_rows, :n].min()) * buckets
    high = float(matrix[:regret_rows, :n].max()) * buckets
    equality = np.r_[np.ones(n), 0.0]
    relaxation = linprog(
        objective,
        A_ub=matrix,
        b_ub=rhs,
        A_eq=equality[None, :],
        b_eq=[buckets],
        bounds=[(0, buckets)] * n + [(low, high)],
        method="highs",
        options={
            "primal_feasibility_tolerance": 1e-9,
            "dual_feasibility_tolerance": 1e-9,
        },
    )
    if not relaxation.success:
        raise ValueError("finite certificate relaxation must be feasible")
    # Reconstruct a bounded-variable dual bound; do not assume reduced costs are exact.
    y = np.minimum(relaxation.ineqlin.marginals, 0.0)
    multiplier = float(relaxation.eqlin.marginals[0])
    residual = objective - matrix.T @ y - multiplier * equality
    base = float(
        y @ rhs
        + multiplier * buckets
        + buckets * np.minimum(residual[:n], 0.0).sum()
        + min(low * residual[-1], high * residual[-1])
        - 1e-4
    )
    if base >= 0:
        return base / 1e6
    # A used integer column contributes at least one unit of positive residual.
    # Any removed column therefore has its own retained global lower bound.
    keep = np.flatnonzero(base + residual[:n] <= 1e-3)
    removed = np.setdiff1d(np.arange(n), keep)
    excluded_bound = float(np.min(base + residual[removed])) if len(removed) else np.inf
    if not len(keep):
        return excluded_bound / 1e6
    # Search only the region that could contradict the requested anchor. Every
    # omitted allocation has objective >=0 by this same reconstructed dual.
    costs = np.maximum(residual[keep], 0.0)
    caps = np.minimum(buckets, np.floor((-base + 1e-3) / np.maximum(costs, 1e-20)))
    excluded_bound = min(excluded_bound, 0.0)
    columns = np.r_[keep, n]
    scaled = matrix[:, columns].copy()
    # Scale the epigraph variable as well as the objective and constraint rows.
    scaled[:, :-1] *= 1e6
    reduced = sparse.vstack(
        [
            sparse.csr_matrix(scaled),
            sparse.csr_matrix(equality[columns][None, :]),
        ],
        format="csr",
    )
    result = milp(
        np.r_[np.zeros(len(keep)), 1.0],
        integrality=np.r_[np.ones(len(keep)), 0.0],
        bounds=Bounds(
            np.r_[np.zeros(len(keep)), low * 1e6], np.r_[caps, min(high, 0.0) * 1e6]
        ),
        constraints=LinearConstraint(
            reduced,
            np.r_[np.full(len(rhs), -np.inf), buckets],
            np.r_[rhs * 1e6, buckets],
        ),
        options={"time_limit": 90.0, "mip_rel_gap": 1e-7},
    )
    bound = np.inf if result.status == 2 else getattr(result, "mip_dual_bound", None)
    if bound is None or not np.isfinite(min(bound, excluded_bound)):
        raise ValueError("finite bank has no solver-certified global bound")
    return float(min(bound, excluded_bound) / 1e6)


def feasible_projection(model, population):
    """Repair only numerical roundoff; never amplify a tolerated invalid population."""
    q = np.asarray(population, dtype=float)
    if hasattr(model, "engines"):
        indices = np.concatenate(
            [start + np.arange(e.nq) for start, e in zip(model.offsets, model.engines)]
        )
    else:
        indices = np.arange(model.nq)
    original = q.ravel()
    m = len(original)
    n = model.n
    select = sparse.csr_matrix((np.ones(m), (np.arange(m), indices)), shape=(m, n))
    distance = sparse.csr_matrix(-np.ones((m, 1)))
    A = sparse.vstack(
        [
            sparse.hstack([model.A_ub, sparse.csr_matrix((model.A_ub.shape[0], 1))]),
            sparse.hstack([select, distance]),
            sparse.hstack([-select, distance]),
        ],
        format="csr",
    )
    E = sparse.hstack(
        [model.A_eq, sparse.csr_matrix((model.A_eq.shape[0], 1))], format="csr"
    )
    result = linprog(
        np.r_[np.zeros(n), 1.0],
        A_ub=A,
        b_ub=np.r_[model.b_ub, original, -original],
        A_eq=E,
        b_eq=model.b_eq,
        bounds=np.vstack([model.bounds, [0, np.inf]]),
        method="highs",
        options={
            "primal_feasibility_tolerance": 1e-10,
            "dual_feasibility_tolerance": 1e-10,
        },
    )
    if not result.success or result.x[-1] > FEAS_TOL:
        raise ValueError(
            "certificate population is not within probability tolerance of the compatible set"
        )
    return result.x[indices].reshape(q.shape)


class CertificateAudit:
    def __init__(self, audit):
        self.audit = audit
        self.p = audit.p
        self.space = audit.space
        self._decisions = {}
        self._changes = {}
        self._regret_rows = {}
        self._safety_rows = {}

    def decisions(self, node, mode):
        key = (node, mode)
        if key not in self._decisions:
            p = self.p
            rows = self.space.encoded[:, p.node_index[node], :]
            models = np.array(
                [
                    [
                        p.cols[p.templates[t].deployments[mode]][i]
                        for t in p.template_ids
                    ]
                    for i in range(p.N)
                ],
                dtype=bool,
            )
            self._decisions[key] = models[
                np.arange(p.N)[None, :], rows[:, p.stratum_of]
            ]
        return self._decisions[key]

    def regret_row(self, q, path, comparator):
        key = (path, comparator, q.tobytes())
        if key in self._regret_rows:
            return self._regret_rows[key]
        p = self.p
        out = np.zeros(len(self.space.policies))
        nodes = p.regret_paths[path]
        for t, node in enumerate(nodes):
            dec = self.decisions(node, p.node_map[node]["mode"])
            pop = q[t]
            out += p.period_weights[t] * (
                dec @ (p.fp * pop[:, 0] - p.fn * pop[:, 1]) + np.sum(p.fn * pop[:, 1])
            )
            if t:
                parent = nodes[t - 1]
                edge_key = (parent, node)
                if edge_key not in self._changes:
                    self._changes[edge_key] = np.logical_xor(
                        self.decisions(parent, p.node_map[parent]["mode"]), dec
                    )
                out += p.switch_weights[t] * (
                    self._changes[edge_key] @ (p.switch * pop.sum(axis=1))
                )
        self._regret_rows[key] = out - sum(
            float((a * b).sum())
            for a, b in zip(p.comparator_trajectory_loss(comparator, path), q)
        )

        return self._regret_rows[key]

    def safety_row(self, q, requirement):
        p = self.p
        mid, sense, threshold = requirement
        key = (mid, q.tobytes())
        if key in self._safety_rows:
            return self._safety_rows[key]
        metric = p.metrics[mid]
        zero = coefficients(
            metric.kind, np.zeros(p.N), p.cols["inc"], metric.scope, p.fp, p.fn
        )
        one = coefficients(
            metric.kind, np.ones(p.N), p.cols["inc"], metric.scope, p.fp, p.fn
        )
        if sense == "le":
            a = zero[0] - threshold * zero[1]
            b = one[0] - threshold * one[1]
        else:
            a = threshold * zero[1] - zero[0]
            b = threshold * one[1] - one[0]
        self._safety_rows[key] = self.decisions(metric.node, metric.mode) @ np.sum(
            (b - a) * q, axis=1
        ) + float((a * q).sum())

        return self._safety_rows[key]

    def lower_bound(self, evaluation, witnesses):
        bank = evaluation["certificate"]
        anchor = bank["lower_bound"]
        rows = []
        rhs = []
        projected = {}

        def repair(model, q):
            key = (id(model), q.tobytes())
            if key not in projected:
                projected[key] = feasible_projection(model, q)
            return projected[key]

        denominators = []
        channel = self.audit.channel
        requirements = {r[0]: r for r in self.p.requirements}
        for desc, q in zip(bank["regret"], witnesses["certificate__regret"]):
            repaired = repair(self.audit.trajectory, q)
            alpha = desc["calibration"]
            group = desc["exposure"]
            ell = channel.probabilities(alpha)
            den = channel.mass(group, alpha)
            numerator = den * self.space.fixed
            for record, response in desc["responses"].items():
                numerator = numerator + ell[
                    :, channel.records.index(record)
                ] * self.regret_row(repaired, response["path"], response["comparator"])
            rows.append(np.r_[numerator - anchor * den, -1.0])
            rhs.append(0.0)
            denominators.append(
                (
                    max(float(den.min()), channel.floors[group] - GATE_EPS),
                    float(den.max()),
                )
            )
        for desc, q in zip(bank["safety"], witnesses["certificate__safety"]):
            mid = desc["metric"]
            repaired = repair(self.audit.engines[self.p.metrics[mid].forecast], q)
            row = self.safety_row(repaired, requirements[mid]) * channel.mass(
                desc["exposure"], desc["calibration"]
            )
            rows.append(np.r_[row, 0.0])
            rhs.append(GATE_EPS)
        # Every sampled floor is a necessary universal constraint. A subset
        # remains a lower-bounding relaxation; never impose unattainable kernel controls.
        calibrations = set(SAMPLES)
        calibrations.update(
            tuple(d["calibration"]) for d in bank["regret"] + bank["safety"]
        )
        for alpha in sorted(calibrations):
            for group, floor in channel.floors.items():
                rows.append(np.r_[-channel.mass(group, alpha), 0.0])
                rhs.append(-floor + GATE_EPS)
        buckets = self.p.rollout_buckets
        matrix = np.array(rows)
        matrix[:, :-1] /= buckets
        rho = integer_margin_bound(
            matrix, np.asarray(rhs), buckets, len(bank["regret"])
        )
        minimum = min(d[0] for d in denominators)
        maximum = max(d[1] for d in denominators)
        # For every lottery, max_i(N_i-anchor*D_i)>=rho and min D<=D_i<=max D.
        # Choosing the denominator by rho's sign preserves a global ratio bound.
        return anchor + rho / (maximum if rho >= 0 else minimum)
