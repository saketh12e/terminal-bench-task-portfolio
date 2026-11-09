"""Independent vectorized public-record likelihoods and calibration validation."""

import numpy as np
from planner_evaluator import EvidenceError, MODELS, is_num


class Disclosure:
    def __init__(self, problem, space):
        self.p = problem
        data = problem.disclosure
        self.records = tuple(data["records"])
        if len(set(self.records)) != len(self.records):
            raise EvidenceError("duplicate public record")
        if data["calibration_domain"] != "a>=0,b>=0,a+b<=1":
            raise EvidenceError("unknown calibration domain")
        if data["profile_counts"] != [
            [2, 0, 0],
            [0, 2, 0],
            [0, 0, 2],
            [1, 1, 0],
            [1, 0, 1],
            [0, 1, 1],
        ]:
            raise EvidenceError("invalid categorical count order")
        self.groups = {g["id"]: tuple(g["records"]) for g in data["exposures"]}
        self.floors = {g["id"]: g["min_probability"] for g in data["exposures"]}
        if any(
            not v or len(set(v)) != len(v) or not set(v) <= set(self.records)
            for v in self.groups.values()
        ):
            raise EvidenceError("invalid exposure records")
        index = {m: i for i, m in enumerate(MODELS)}
        slots = data["slots"]
        shape = (len(MODELS),) * len(slots) + (len(self.records),)
        tables = np.full((6,) + shape, np.nan)
        for row in data["kernels"]:
            key = tuple(index[m] for m in row["models"])
            if np.isfinite(tables[(0,) + key]).all():
                raise EvidenceError("duplicate channel signature")
            profiles = np.asarray(row["profiles"], dtype=float)
            if profiles.shape != (6, len(self.records)):
                raise EvidenceError(
                    "two-probe kernels require six count-conditioned rows"
                )
            for j in range(6):
                tables[(j,) + key] = profiles[j]
        if (
            not np.isfinite(tables).all()
            or (tables <= 0).any()
            or np.max(abs(tables.sum(axis=-1) - 1)) > 1e-12
        ):
            raise EvidenceError("channel rows must be positive probabilities")
        coordinates = []
        for slot in slots:
            node = slot["node"]
            mode = problem.node_map[node]["mode"]
            models = np.array(
                [
                    index[problem.templates[t].deployments[mode]]
                    for t in problem.template_ids
                ]
            )
            coordinates.append(
                models[space.encoded[:, problem.node_index[node], slot["stratum"]]]
            )
        self.controls = np.stack([t[tuple(coordinates)] for t in tables])

    def valid_calibration(self, point):
        return (
            isinstance(point, (tuple, list))
            and len(point) == 2
            and all(is_num(x) for x in point)
            and min(point) >= 0
            and sum(point) <= 1
        )

    def probabilities(self, calibration):
        if not self.valid_calibration(calibration):
            raise ValueError("calibration outside joint simplex")
        a, b = calibration
        c = 1 - a - b
        return np.einsum(
            "j,jkr->kr",
            [a * a, b * b, c * c, 2 * a * b, 2 * a * c, 2 * b * c],
            self.controls,
        )

    def mass(self, group, calibration):
        indices = [self.records.index(r) for r in self.groups[group]]
        return self.probabilities(calibration)[:, indices].sum(axis=1)
