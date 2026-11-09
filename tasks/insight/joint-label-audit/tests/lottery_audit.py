"""Full-label sharp bounds with a common population across public records."""

import itertools
import numpy as np
from planner_evaluator import Engine, TrajectoryEngine, FEAS_TOL, VALUE_TOL
from tree_space import StructuralTrees
from disclosure import Disclosure
from calibration import curve_maximum, response_maximum, minimum_probability


class LotteryAudit:
    def __init__(self, problem, evaluation):
        self.p = problem
        self.e = evaluation
        self.space = StructuralTrees(problem)
        self.channel = Disclosure(problem, self.space)
        self.engines = {f: Engine(problem, f) for f in problem.forecasts}
        self.trajectory = TrajectoryEngine(problem, self.engines)
        self.weights = np.zeros(len(self.space.policies))
        for policy, weight in evaluation["mixture"]:
            if policy not in self.space.lookup:
                raise ValueError("positive-count tree violates structural constraints")
            self.weights[self.space.lookup[policy]] += weight
        self.support = np.flatnonzero(self.weights)
        self.responses = list(
            itertools.product(problem.regret_paths, problem.comparator_ids)
        )
        self.allowed = {
            r: [
                x
                for x in self.responses
                if x[0] in problem.disclosure["record_paths"][r]
            ]
            for r in self.channel.records
        }
        self._serial = itertools.count()
        self._forms = {}
        self._record = {}
        self._scenarios = None
        self._endpoints = {}
        self.loss = {
            path: np.array(
                [
                    problem.trajectory_loss(self.space.policies[j], path)
                    for j in self.support
                ]
            )
            for path in problem.regret_paths
        }

    def forms(self, metric, group, alpha):
        key = (metric, group, tuple(alpha))
        if key not in self._forms:
            weighted = self.weights * self.channel.mass(group, alpha)
            pairs = [
                (weighted[j], self.p.forms(self.space.policies[j], metric))
                for j in self.support
            ]
            self._forms[key] = (
                sum(w * x[0] for w, x in pairs),
                sum(w * x[1] for w, x in pairs),
            )
        return self._forms[key]

    def record_coefficient(self, record, alpha, path, comp):
        key = (record, tuple(alpha), path, comp)
        if key not in self._record:
            r = self.channel.records.index(record)
            w = (
                self.weights[self.support]
                * self.channel.probabilities(alpha)[self.support, r]
            )
            self._record[key] = np.einsum(
                "k,ktnl->tnl", w, self.loss[path]
            ) - w.sum() * np.array(self.p.comparator_trajectory_loss(comp, path))
        return self._record[key]

    def scenario_value(self, desc, q, include_cost):
        group = desc["exposure"]
        alpha = desc["calibration"]
        coef = 0.0
        for record, response in desc["responses"].items():
            coef = coef + self.record_coefficient(
                record, alpha, response["path"], response["comparator"]
            )
        mass = self.weights * self.channel.mass(group, alpha)
        return (
            float((coef * q).sum())
            + (float(mass @ self.space.fixed) if include_cost else 0.0)
        ) / mass.sum()

    def form_controls(self, metric, group):
        ids = [self.channel.records.index(r) for r in self.channel.groups[group]]
        masses = self.channel.controls[:, :, ids].sum(axis=-1)
        pair = np.array(
            [self.p.forms(self.space.policies[j], metric) for j in self.support]
        )
        return np.einsum(
            "ak,ksnl->asnl", masses[:, self.support] * self.weights[self.support], pair
        )

    def exposure_minimum(self, group):
        ids = [self.channel.records.index(r) for r in self.channel.groups[group]]
        masses = self.channel.controls[:, :, ids].sum(axis=-1) @ self.weights
        return minimum_probability(masses)

    def scenarios(self):
        if self._scenarios is not None:
            return self._scenarios
        out = []
        for group, records in self.channel.groups.items():
            coefficients = {}
            marginal = {}
            for record in records:
                r = self.channel.records.index(record)
                w = (
                    self.channel.controls[:, self.support, r]
                    * self.weights[self.support]
                )
                for path, comp in self.allowed[record]:
                    c = np.einsum("ak,ktnl->atnl", w, self.loss[path])
                    c -= w.sum(axis=1)[:, None, None, None] * np.array(
                        self.p.comparator_trajectory_loss(comp, path)
                    )
                    coefficients[record, path, comp] = c
                    marginal[record, path, comp] = np.array(
                        [
                            self.trajectory.linear_max(
                                x, ("curve-marginal", next(self._serial))
                            )[0]
                            for x in c
                        ]
                    )
            indices = [self.channel.records.index(r) for r in records]
            mass = self.channel.controls[:, :, indices].sum(axis=-1) * self.weights
            den = mass.sum(axis=1)
            cost = mass @ self.space.fixed
            cached = {}

            def oracle(packed):
                coeff = packed[:-1].reshape(len(self.p.period_weights), self.p.N, 2)
                key = coeff.tobytes()
                if key not in cached:
                    cached[key] = self.trajectory.linear_max(
                        coeff, ("curve-response", next(self._serial))
                    )
                val, q = cached[key]
                return val + packed[-1], q

            for include_cost in [False, True]:
                cases = []
                for responses in itertools.product(*(self.allowed[r] for r in records)):
                    c = sum(coefficients[(r,) + z] for r, z in zip(records, responses))
                    extra = cost if include_cost else np.zeros(6)
                    packed = np.column_stack([c.reshape(6, -1), extra])
                    bound = (
                        sum(marginal[(r,) + z] for r, z in zip(records, responses))
                        + extra
                    )
                    cases.append((responses, packed, bound))
                val, alpha, (responses, q), upper = response_maximum(cases, den, oracle)
                desc = {
                    "exposure": group,
                    "calibration": alpha,
                    "responses": {
                        r: {"path": z[0], "comparator": z[1]}
                        for r, z in zip(records, responses)
                    },
                }
                regret = self.scenario_value(desc, q, False)
                score = self.scenario_value(desc, q, True)
                out.append((regret, score, desc, q))
        self._scenarios = out
        return out

    def gate(self, requirement, group):
        mid, sense, threshold = requirement
        pairs = self.form_controls(mid, group)
        controls = pairs[:, 0] - threshold * pairs[:, 1]
        if sense == "ge":
            controls = -controls

        def oracle(c):
            return self.engines[self.p.metrics[mid].forecast].linear_max(
                c, ("curve-gate", next(self._serial))
            )

        return curve_maximum(controls, oracle, tolerance=2e-12, threshold=1e-9)

    def endpoint(self, metric, group, side):
        key = (metric, group, side)
        if key not in self._endpoints:
            controls = self.form_controls(metric, group)
            sign = 1 if side == "hi" else -1

            def oracle(pair):
                val, q = self.engines[self.p.metrics[metric].forecast].extremum(
                    pair[0], pair[1], side, ("curve-endpoint", next(self._serial))
                )
                return sign * val, q

            val, alpha, q, upper = curve_maximum(controls, oracle)
            self._endpoints[key] = (sign * val, alpha, q)
        return self._endpoints[key]

    def score(self):
        return max(r[1] for r in self.scenarios())

    def endpoint_errors(self, witnesses, mid, group, side):
        i = ("lo", "hi").index(side)
        reported = self.e["bounds"][group][mid][i]
        alpha = self.e["metric_calibrations"][group][mid][i]
        q = witnesses[group + "__" + mid + "__" + side]
        engine = self.engines[self.p.metrics[mid].forecast]
        bad = {k: v for k, v in engine.residuals(q).items() if v > FEAS_TOL}
        if bad:
            return ["incompatible endpoint population: " + str(bad)]
        num, den = self.forms(mid, group, alpha)
        divisor = float((den * q).sum())
        if divisor <= 0:
            return ["nonpositive witness denominator"]
        value = float((num * q).sum()) / divisor
        sign = 1 if side == "hi" else -1
        # Both the report and the submitted witness must lie within VALUE_TOL
        # of the true signed maximum. Certify their interval intersection.
        lower = max(sign * reported, sign * value) - VALUE_TOL
        upper = min(sign * reported, sign * value) + VALUE_TOL
        if lower > upper:
            return ["report and attaining witness cannot share a sharp endpoint"]
        controls = self.form_controls(mid, group)

        def residual_bound(target):
            coefficients = sign * controls[:, 0] - target * controls[:, 1]

            def oracle(c):
                return engine.linear_max(c, ("endpoint-proof", next(self._serial)))

            return curve_maximum(coefficients, oracle, tolerance=1e-12, threshold=0.0)

        # One independent population optimum seeds a valid lower bound. The
        # submitted population itself may have tolerated residuals and therefore
        # is never used as proof that a global maximum is at least its value.
        attained = (
            sign
            * engine.extremum(num, den, side, ("endpoint-seed", next(self._serial)))[0]
        )
        lower_proved = attained >= lower
        if not lower_proved:
            result = residual_bound(lower)
            lower_proved = result[0] >= 0
            if result[3] < -1e-12:
                return ["reported endpoint or witness lies above the sharp maximum"]
        result = residual_bound(upper)
        if result[3] <= 0 and lower_proved:
            return []
        if result[0] > 1e-12:
            return [
                "a compatible calibration/population exceeds the claimed endpoint interval"
            ]
        # Exact-threshold roundoff and legitimate opposite tolerance-boundary
        # offsets retain the full independent sharp computation as a fallback.
        truth = self.endpoint(mid, group, side)[0]
        errors = []
        if abs(truth - reported) > VALUE_TOL:
            errors.append(f"reported {reported:.9g}; sharp {side} {truth:.9g}")
        if abs(value - truth) > VALUE_TOL:
            errors.append(f"witness attains {value:.9g}; expected {truth:.9g}")
        return errors
