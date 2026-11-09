"""Repeated attestation with one common calibration and population."""

import itertools
import numpy as np
from audit_primitives import Valuation, TreeSpace
from calibration import maximize, maximize_cases, evaluate, minimum_quadratic, SAMPLES


class DisclosureModel:
    def __init__(self, data):
        self.data = data
        self.v = Valuation(data)
        self.space = TreeSpace(self.v)
        self.k = len(self.space.policies)
        d = data["disclosure"]
        table = {tuple(r["models"]): np.array(r["profiles"]) for r in d["kernels"]}
        self.controls = np.stack(
            [
                table[
                    tuple(
                        self.v.templates[
                            tree[self.v.node_index[s["node"]]][s["stratum"]]
                        ]["deployments"][self.v.node_map[s["node"]]["mode"]]
                        for s in d["slots"]
                    )
                ]
                for tree in self.space.policies
            ],
            axis=1,
        )
        self.likelihood = {a: evaluate(self.controls, a) for a in SAMPLES}
        self.groups = {
            g["id"]: [d["records"].index(s) for s in g["records"]]
            for g in d["exposures"]
        }
        self.responses = [
            (p["id"], c)
            for p in data["planning"]["regret_paths"]
            for c in self.v.comparators
        ]
        self.allowed = {
            r: [x for x in self.responses if x[0] in d["record_paths"][record]]
            for r, record in enumerate(d["records"])
        }
        self.paths = {x["id"]: x for x in data["planning"]["regret_paths"]}
        self._counter = itertools.count()

    def metric_controls(self, weights, group, mid):
        support = np.flatnonzero(weights > 1e-14)
        forms = [self.v.forms(self.space.policies[j], mid) for j in support]
        mass = (
            self.controls[:, :, self.groups[group]].sum(axis=-1)[:, support]
            * weights[support]
        )
        return np.einsum("ak,ksnl->asnl", mass, np.array(forms))

    def endpoint(self, weights, group, mid, high):
        controls = self.metric_controls(weights, group, mid)
        eng = self.v.engines[self.v.metrics[mid]["forecast"]]
        sign = 1 if high else -1

        def oracle(pair):
            val, q = eng.extreme(pair[0], pair[1], high, ("curve", next(self._counter)))
            return sign * val, q

        val, alpha, q, upper = maximize(controls, oracle)
        return sign * val, alpha, q

    def separate(self, weights, iteration):
        support = np.flatnonzero(weights > 1e-14)
        losses = {
            p: np.array(
                [self.v.trajectory_loss(self.space.policies[j], path) for j in support]
            )
            for p, path in self.paths.items()
        }
        comps = {
            z: np.array(self.v.comparator_trajectory_loss(z[1], self.paths[z[0]]))
            for z in self.responses
        }
        risks = []
        gates = []
        self.floor_bad = 0.0
        for group, records in self.groups.items():
            coef = {}
            bounds = {}
            for r in records:
                w = self.controls[:, support, r] * weights[support]
                for z in self.allowed[r]:
                    c = (
                        np.einsum("ak,ktnl->atnl", w, losses[z[0]])
                        - w.sum(axis=1)[:, None, None, None] * comps[z]
                    )
                    coef[r, z] = c
                    bounds[r, z] = np.array(
                        [
                            self.v.trajectory.linear_max(
                                x, ("curve", next(self._counter))
                            )[0]
                            for x in c
                        ]
                    )
            mass = self.controls[:, :, records].sum(axis=-1) * weights
            den = mass.sum(axis=1)
            cost = mass @ self.space.fixed
            cache = {}

            def oracle(packed):
                c = packed[:-1].reshape(len(self.v.trajectory.engines), self.v.n, 2)
                key = c.tobytes()
                if key not in cache:
                    cache[key] = self.v.trajectory.linear_max(
                        c, ("curve", next(self._counter))
                    )
                val, q = cache[key]
                return val + packed[-1], q

            for include_cost in [True] if iteration != "final" else [False, True]:
                cases = []
                for choices in itertools.product(*(self.allowed[r] for r in records)):
                    c = sum(coef[r, z] for r, z in zip(records, choices))
                    const = cost if include_cost else np.zeros(6)
                    packed = np.column_stack([c.reshape(6, -1), const])
                    ub = sum(bounds[r, z] for r, z in zip(records, choices)) + const
                    cases.append((choices, packed, ub))
                value, alpha, (choices, q), upper = maximize_cases(cases, den, oracle)
                conditional_cost = float(evaluate(cost, alpha) / evaluate(den, alpha))
                regret = value - (conditional_cost if include_cost else 0)
                risks.append(
                    (regret, regret + conditional_cost, group, alpha, choices, q)
                )
                self.likelihood[alpha] = evaluate(self.controls, alpha)
            for req in self.data["planning"]["requirements"]:
                mid = req["metric"]
                pairs = self.metric_controls(weights, group, mid)
                c = pairs[:, 0] - req["threshold"] * pairs[:, 1]
                if req["sense"] == "ge":
                    c = -c
                eng = self.v.engines[self.v.metrics[mid]["forecast"]]

                def oracle(coef):
                    return eng.linear_max(coef, ("gatecurve", next(self._counter)))

                val, alpha, q, upper = maximize(
                    c, oracle, tolerance=2e-12, threshold=1e-9
                )
                self.likelihood[alpha] = evaluate(self.controls, alpha)
                gates.append((val, group, alpha, req, q))
            floor = next(
                g["min_probability"]
                for g in self.data["disclosure"]["exposures"]
                if g["id"] == group
            )
            mass = self.controls[:, :, records].sum(axis=-1) @ weights
            value, alpha = minimum_quadratic(mass)
            self.floor_bad = max(self.floor_bad, floor - value)
            if value < floor - 1e-9:
                self.likelihood[alpha] = evaluate(self.controls, alpha)
        return risks, gates
