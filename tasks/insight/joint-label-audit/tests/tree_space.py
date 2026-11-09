"""Independent structural tree enumeration; no per-tree statistical filtering."""

import math
import numpy as np
from planner_evaluator import MODELS, MAX_TREES, SolverError


class StructuralTrees:
    def __init__(self, problem):
        self.p = problem
        self.encoded, self.fixed = self._enumerate()
        self.policies = tuple(
            tuple(tuple(problem.template_ids[t] for t in row) for row in tree)
            for tree in self.encoded
        )
        self.lookup = {policy: i for i, policy in enumerate(self.policies)}

    def _local_rows(self, node_id):
        """All template rows for one node that satisfy its node-local architecture rows."""
        p, nt = self.p, len(self.p.template_ids)
        local = [
            (
                np.asarray(strata, dtype=np.int64),
                np.array(sorted({p.template_ids.index(t) for t in tids})),
                lower,
                upper,
            )
            for _, nodes, strata, tids, lower, upper in p.architecture_constraints
            if set(nodes) == {node_id}
        ]
        rows = np.zeros((1, 0), dtype=np.int64)
        for s in range(p.S):
            rows = np.hstack(
                [
                    np.repeat(rows, nt, axis=0),
                    np.tile(np.arange(nt), len(rows))[:, None],
                ]
            )
            keep = np.ones(len(rows), dtype=bool)
            for strata, tids, lower, upper in local:
                count = np.isin(rows[:, strata[strata <= s]], tids).sum(axis=1)
                remaining = int((strata > s).sum())
                keep &= (count <= upper) & (count + remaining >= lower)
            rows = rows[keep]
        return rows

    def _enumerate(self):
        """Enumerate structural trees without applying lottery-level safety gates."""
        p, S = self.p, self.p.S
        rows = [self._local_rows(node_id) for node_id in p.node_ids]
        sizes = [len(r) for r in rows]
        total = math.prod(sizes)
        if total == 0:
            raise SolverError(
                f"no eligible local template rows: {dict(zip(p.node_ids, sizes))}"
            )
        if total > MAX_TREES:
            raise SolverError(
                f"{total} candidate trees exceed the enumeration bound {MAX_TREES}"
            )
        grid = np.stack(
            np.meshgrid(*[np.arange(n) for n in sizes], indexing="ij"), axis=-1
        ).reshape(-1, len(sizes))
        costs = np.array([p.templates[t].deployment_costs for t in p.template_ids])
        stratum_switch = np.array([p.switch[p.stratum_of == s][0] for s in range(S)])
        deployed = []
        for i, node in enumerate(p.nodes):
            table = np.array(
                [
                    MODELS.index(p.templates[t].deployments[node["mode"]])
                    for t in p.template_ids
                ]
            )
            deployed.append(table[rows[i]])
        ok = np.ones(total, dtype=bool)
        fixed = np.zeros(total)
        for i, node in enumerate(p.nodes):
            fixed += (node["cost_weight"] * costs[rows[i], np.arange(S)].sum(axis=1))[
                grid[:, i]
            ]
        tree_rows = [row for row in p.architecture_constraints if len(set(row[1])) > 1]
        for _, nodes, strata, tids, lower, upper in tree_rows + list(
            p.fleet_constraints
        ):
            tidx = sorted({p.template_ids.index(t) for t in tids})
            count = np.zeros(total, dtype=np.int64)
            for node_id in set(nodes):
                i = p.node_index[node_id]
                count += np.isin(rows[i][:, list(strata)], tidx).sum(axis=1)[grid[:, i]]
            ok &= (count >= lower) & (count <= upper)
        for parent, child in p.edges:
            a, b = p.node_index[parent], p.node_index[child]
            changed = deployed[a][:, None, :] != deployed[b][None, :, :]
            weight = p.node_map[child]["reconfiguration_weight"]
            fixed += (weight * (changed * stratum_switch).sum(axis=2))[
                grid[:, a], grid[:, b]
            ]
            for _, edge, strata, cap in p.reconfiguration_constraints:
                if edge == (parent, child):
                    ok &= (
                        changed[:, :, list(strata)].sum(axis=2)[grid[:, a], grid[:, b]]
                        <= cap
                    )
        feasible = np.flatnonzero(ok)
        if feasible.size == 0:
            raise SolverError("no policy tree satisfies every eligibility constraint")
        encoded = np.stack(
            [rows[i][grid[feasible, i]] for i in range(len(rows))], axis=1
        )
        return encoded, fixed[feasible]
