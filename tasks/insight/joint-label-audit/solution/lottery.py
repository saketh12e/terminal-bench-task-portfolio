"""Certify a robust integer rollout under a shared calibration simplex."""

import time
import numpy as np
from scipy.optimize import linprog
from disclosure import DisclosureModel


class RolloutGame(DisclosureModel):
    def __init__(self, data):
        super().__init__(data)
        self.cuts = []

    def add(self, risks, gates, target, seed=False):
        for regret, score, group, alpha, choices, q in risks:
            if seed or score > target + 1e-10:
                records = self.groups[group]
                ell = self.likelihood[alpha]
                den = ell[:, records].sum(axis=1)
                row = (
                    sum(
                        ell[:, record] * self.space.risk_row(q, *choice)
                        for record, choice in zip(records, choices)
                    )
                    + den * self.space.fixed
                )
                self.cuts.append(("risk", row, den, (group, alpha, choices, q)))
        for val, group, alpha, req, q in gates:
            if val > 1e-10:
                den = self.likelihood[alpha][:, self.groups[group]].sum(axis=1)
                self.cuts.append(
                    (
                        "safety",
                        den * self.space.safety_row(q, req),
                        None,
                        (group, alpha, req, q),
                    )
                )

    def master(self, target, integral):
        scale = self.data["planning"]["rollout_buckets"] if integral else 1
        rows = [
            np.r_[
                (row - target * den if kind == "risk" else row) / scale,
                -1.0 if kind == "risk" else 0.0,
            ]
            for kind, row, den, _ in self.cuts
        ]
        rhs = [0.0 if kind == "risk" else 1e-9 for kind, _, _, _ in self.cuts]
        for alpha, ell in self.likelihood.items():
            for g in self.data["disclosure"]["exposures"]:
                den = ell[:, self.groups[g["id"]]].sum(axis=1)
                rows.append(np.r_[-den / scale, 0.0])
                rhs.append(-g["min_probability"] + 1e-9)
        rows = np.array(rows)
        obj = np.r_[np.zeros(self.k), 1e6]
        if integral:
            from integer_master import margin_master

            res = margin_master(rows, np.asarray(rhs), scale)
            if res.x is None:
                raise RuntimeError(res.message)
            weights = np.rint(res.x[:-1]) / scale
            rho = res.mip_dual_bound / 1e6
        else:
            res = linprog(
                obj,
                A_ub=rows,
                b_ub=rhs,
                A_eq=np.r_[np.ones(self.k), 0][None, :],
                b_eq=[1],
                bounds=[(0, None)] * self.k + [(None, None)],
                method="highs",
                options={
                    "primal_feasibility_tolerance": 1e-9,
                    "dual_feasibility_tolerance": 1e-9,
                },
            )
            if not res.success:
                raise RuntimeError(res.message)
            weights = np.maximum(0, res.x[:-1])
            weights /= weights.sum()
            rho = res.fun / 1e6
        minimum = min(
            float(den.min()) for kind, _, den, _ in self.cuts if kind == "risk"
        )
        maximum = max(
            float(den.max()) for kind, _, den, _ in self.cuts if kind == "risk"
        )
        lower = target + rho / (maximum if rho >= 0 else minimum)
        finite = max(
            float(row @ weights / (den @ weights))
            for kind, row, den, _ in self.cuts
            if kind == "risk"
        )
        return weights, lower, finite, res

    def solve(self):
        weights = np.zeros(self.k)
        weights[np.argmin(self.space.fixed)] = 1
        target = 0.05
        risks, gates = self.separate(weights, -1)
        self.add(risks, gates, target, True)
        integer = False
        for iteration in range(100):
            t = time.monotonic()
            weights, lower, finite, res = self.master(target, integer)
            risks, gates = self.separate(weights, iteration)
            upper = max(r[1] for r in risks)
            bad = max(max(g[0] for g in gates), self.floor_bad)
            print(
                "ITER",
                iteration,
                "integer",
                integer,
                "support",
                sum(weights > 0),
                "lower",
                lower,
                "upper",
                upper,
                "gap",
                upper - lower,
                "gate",
                bad,
                "cuts",
                len(self.cuts),
                "time",
                time.monotonic() - t,
                flush=True,
            )
            # The continuous master only seeds cuts; do not spend time certifying
            # its rounding-scale residuals. The final integer allocation still
            # has to meet the full public safety and optimality tolerances.
            if not integer and bad <= 1e-7 and upper - lower < 1e-6:
                integer = True
            elif integer and bad <= 1e-9 and upper - lower < 2e-7:
                return weights, self.separate(weights, "final")[0], self.cuts, lower
            self.add(risks, gates, finite)
            target = upper if bad <= 1e-9 else finite
        raise RuntimeError("no convergence")
