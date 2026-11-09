"""Reduced latent-label population and drift-coupled trajectory programs."""

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import block_diag, csr_matrix, hstack, vstack


class ForecastModel:
    """Compact LP with one phishing-mass variable per cell plus stratum weights."""

    def __init__(self, data, forecast):
        self.data, self.cells = data, data["cells"]
        self.n, self.s = len(self.cells), len(data["strata"])
        self.k = self.n + 2 * self.s
        self.sid = np.array([cell["stratum"] for cell in self.cells])
        counts = np.array([cell["count"] for cell in self.cells], dtype=float)
        self.share = counts / np.bincount(self.sid, weights=counts)[self.sid]
        self.forecast = next(row for row in data["forecasts"] if row["id"] == forecast)
        self.rows, self.rhs = [], []
        for i, s in enumerate(self.sid):
            row = np.zeros(self.k)
            row[i], row[self.n + s] = 1, -self.share[i]
            self.add(row, 0)
        for audit in data["audits"]:
            given = self.mass(audit["given"])
            joint = self.mass(audit["given"], audit["event"])
            self.add(joint - audit["upper"] * given, 0)
            self.add(audit["lower"] * given - joint, 0)
            self.add(-given, -audit["min_mass"])
        f = self.forecast
        for s in range(self.s):
            weight = np.zeros(self.k)
            weight[self.n + s] = 1
            dev = np.zeros(self.k)
            dev[self.n + self.s + s] = 1
            self.add(weight, f["upper"][s])
            self.add(-weight, -f["lower"][s])
            self.add(weight - dev, f["nominal"][s])
            self.add(-weight - dev, -f["nominal"][s])
        devs = np.zeros(self.k)
        devs[self.n + self.s :] = 1
        self.add(devs, f["l1_budget"])
        for group in f["groups"]:
            weight = np.zeros(self.k)
            weight[self.n + np.array(group["strata"])] = 1
            self.add(weight, group["upper"])
            self.add(-weight, -group["lower"])
        self.A, self.b = csr_matrix(np.stack(self.rows)), np.array(self.rhs)
        total = np.zeros(self.k)
        total[self.n : self.n + self.s] = 1
        self.E, self.e = csr_matrix(total[None, :]), np.ones(1)
        self._fractional, self._linear = {}, {}

    def add(self, row, rhs):
        self.rows.append(row)
        self.rhs.append(rhs)

    def mass(self, *selectors):
        mask = np.ones((self.n, 2), dtype=bool)
        for selector in selectors:
            for field, allowed in selector.items():
                if field == "label":
                    mask &= np.isin([0, 1], allowed)[None, :]
                else:
                    mask &= np.isin([cell[field] for cell in self.cells], allowed)[
                        :, None
                    ]
        return self.form(mask.astype(float))

    def form(self, qcoef):
        out = np.zeros(self.k)
        out[: self.n] = qcoef[:, 1] - qcoef[:, 0]
        out[self.n : self.n + self.s] = np.bincount(
            self.sid, weights=self.share * qcoef[:, 0], minlength=self.s
        )
        return out

    def to_q(self, x):
        total = self.share * x[self.n + self.sid]
        return np.column_stack((total - x[: self.n], x[: self.n]))

    def extreme(self, num_q, den_q, high, key):
        cache = (key, high)
        if cache not in self._fractional:
            num, den = self.form(num_q), self.form(den_q)
            A = hstack([self.A, csr_matrix(-self.b[:, None])], format="csr")
            E = vstack(
                [
                    hstack([self.E, csr_matrix(-self.e[:, None])]),
                    csr_matrix(np.r_[den, 0][None, :]),
                ],
                format="csr",
            )
            result = linprog(
                np.r_[(-1 if high else 1) * num, 0],
                A_ub=A,
                b_ub=np.zeros(len(self.b)),
                A_eq=E,
                b_eq=[0, 1],
                bounds=(0, None),
                method="highs",
                options={
                    "primal_feasibility_tolerance": 1e-9,
                    "dual_feasibility_tolerance": 1e-9,
                },
            )
            if not result.success or result.x[-1] <= 0:
                raise RuntimeError((key, result.message))
            x = result.x[:-1] / result.x[-1]
            self._fractional[cache] = (float(num @ x / (den @ x)), self.to_q(x))
        return self._fractional[cache]

    def linear_max(self, qcoef, key):
        # Search callers retain selected witnesses; bound the transient LP cache.
        if len(self._linear) >= 256:
            self._linear.clear()
        if key not in self._linear:
            coef = self.form(qcoef)
            result = linprog(
                -coef,
                A_ub=self.A,
                b_ub=self.b,
                A_eq=self.E,
                b_eq=self.e,
                bounds=(0, None),
                method="highs",
                options={
                    "primal_feasibility_tolerance": 1e-9,
                    "dual_feasibility_tolerance": 1e-9,
                },
            )
            if not result.success:
                raise RuntimeError((key, result.message))
            self._linear[key] = (float(coef @ result.x), self.to_q(result.x))
        return self._linear[key]


class TrajectoryModel:
    """Block LP for the coupled sequence of forecast populations."""

    def __init__(self, data, engines):
        planning = data["planning"]
        by_period = {}
        for node in planning["nodes"]:
            by_period.setdefault(node["period"], set()).add(node["forecast"])
        if sorted(by_period) != list(range(len(by_period))) or any(
            len(v) != 1 for v in by_period.values()
        ):
            raise ValueError("each period must have exactly one forecast")
        self.forecast_order = [next(iter(by_period[t])) for t in range(len(by_period))]
        self.engines = [engines[fid] for fid in self.forecast_order]
        self.offsets = np.cumsum([0] + [engine.k for engine in self.engines[:-1]])
        self.k = sum(engine.k for engine in self.engines)
        base = block_diag([engine.A for engine in self.engines], format="csr")
        rhs = list(np.concatenate([engine.b for engine in self.engines]))
        extra = []
        for drift in planning["drift_constraints"]:
            forms = [engine.mass(drift["selector"]) for engine in self.engines]
            for period in range(len(self.engines) - 1):
                row = np.zeros(self.k)
                left, right = self.offsets[period], self.offsets[period + 1]
                row[left : left + self.engines[period].k] = -forms[period]
                row[right : right + self.engines[period + 1].k] = forms[period + 1]
                extra.extend([csr_matrix(row[None, :]), csr_matrix((-row)[None, :])])
                rhs.extend([drift["max_abs"], drift["max_abs"]])
        self.A = vstack([base] + extra, format="csr")
        self.b = np.array(rhs)
        self.E = block_diag([engine.E for engine in self.engines], format="csr")
        self.e = np.ones(len(self.engines))
        self._linear = {}

    def linear_max(self, qcoefs, key):
        # Search callers retain selected witnesses; bound the transient LP cache.
        if len(self._linear) >= 256:
            self._linear.clear()
        if key not in self._linear:
            objective = np.zeros(self.k)
            for period, (engine, qcoef) in enumerate(zip(self.engines, qcoefs)):
                start = self.offsets[period]
                objective[start : start + engine.k] = engine.form(qcoef)
            result = linprog(
                -objective,
                A_ub=self.A,
                b_ub=self.b,
                A_eq=self.E,
                b_eq=self.e,
                bounds=(0, None),
                method="highs",
                options={
                    "primal_feasibility_tolerance": 1e-9,
                    "dual_feasibility_tolerance": 1e-9,
                },
            )
            if not result.success:
                raise RuntimeError((key, result.message))
            populations = np.stack(
                [
                    engine.to_q(result.x[start : start + engine.k])
                    for start, engine in zip(self.offsets, self.engines)
                ]
            )
            self._linear[key] = (float(objective @ result.x), populations)
        return self._linear[key]
