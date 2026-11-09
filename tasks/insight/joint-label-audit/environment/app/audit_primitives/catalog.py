"""Enumerate deployable trees; statistical safety is a property of the lottery."""

from itertools import product
import numpy as np


class TreeSpace:
    def __init__(self, value):
        self.v = value
        data, S, tids = value.data, value.s, value.template_ids
        nodes = value.nodes
        constraints = (
            data["architecture_constraints"] + data["planning"]["fleet_constraints"]
        )
        local = {}
        for node in nodes:
            nid = node["id"]
            rows = []
            choices = []
            rules = [r for r in constraints if set(r["nodes"]) == {nid}]
            for s in range(S):
                allowed = set(tids)
                for rule in rules:
                    if rule["strata"] == [s] and rule["lower"] == 1:
                        allowed &= set(rule["templates"])
                choices.append([t for t in tids if t in allowed])
            for row in product(*choices):
                if all(
                    r["lower"]
                    <= sum(row[s] in r["templates"] for s in r["strata"])
                    <= r["upper"]
                    for r in rules
                ):
                    rows.append(row)
            local[nid] = rows
        global_rules = [r for r in constraints if len(set(r["nodes"])) > 1]
        edges = data["planning"]["reconfiguration_constraints"]
        answers = []

        def visit(chosen):
            if len(chosen) == len(nodes):
                answers.append(tuple(chosen[n["id"]] for n in nodes))
                return
            node = nodes[len(chosen)]
            nid = node["id"]
            for row in local[nid]:
                chosen[nid] = row
                valid = True
                for rule in global_rules:
                    count = sum(
                        chosen[n][s] in rule["templates"]
                        for n in rule["nodes"]
                        if n in chosen
                        for s in rule["strata"]
                    )
                    remaining = sum(n not in chosen for n in rule["nodes"]) * len(
                        rule["strata"]
                    )
                    if count > rule["upper"] or count + remaining < rule["lower"]:
                        valid = False
                        break
                for rule in edges:
                    a, b = rule["parent"], rule["child"]
                    if a in chosen and b in chosen:
                        changes = sum(
                            value.templates[chosen[a][s]]["deployments"][
                                value.node_map[a]["mode"]
                            ]
                            != value.templates[chosen[b][s]]["deployments"][
                                value.node_map[b]["mode"]
                            ]
                            for s in rule["strata"]
                        )
                        if changes > rule["max_changes"]:
                            valid = False
                            break
                if valid:
                    visit(chosen)
                del chosen[nid]

        visit({})
        self.policies = tuple(answers)
        if not answers:
            raise ValueError("no deployable policy trees")
        self.encoded = np.array(
            [[[tids.index(t) for t in row] for row in policy] for policy in answers]
        )
        self.fixed = np.array([value.deployment_cost(p) for p in answers])
        self.dec = {
            (mode, t): value.models[value.templates[tid]["deployments"][mode]].astype(
                float
            )
            for mode in value.modes
            for t, tid in enumerate(tids)
        }

    def risk_row(self, q, path_id, comparator_id):
        v = self.v
        planning = v.data["planning"]
        nodes = next(p["nodes"] for p in planning["regret_paths"] if p["id"] == path_id)
        out = np.zeros(len(self.policies))
        nt = len(v.template_ids)
        for period, node in enumerate(nodes):
            i = v.node_index[node]
            mode = v.node_map[node]["mode"]
            pop = q[period]
            for s in range(v.s):
                mask = v.sid == s
                table = []
                for t in range(nt):
                    dec = self.dec[mode, t][mask]
                    table.append(
                        np.sum(
                            v.fp[mask] * dec * pop[mask, 0]
                            + v.fn[mask] * (1 - dec) * pop[mask, 1]
                        )
                    )
                out += (
                    planning["period_weights"][period]
                    * np.array(table)[self.encoded[:, i, s]]
                )
                if period:
                    parent = v.node_index[nodes[period - 1]]
                    pmode = v.node_map[nodes[period - 1]]["mode"]
                    table = np.empty((nt, nt))
                    for a in range(nt):
                        for b in range(nt):
                            table[a, b] = np.sum(
                                v.switch[mask]
                                * pop[mask].sum(axis=1)
                                * abs(
                                    self.dec[pmode, a][mask] - self.dec[mode, b][mask]
                                )
                            )
                    out += (
                        planning["switch_weights"][period]
                        * table[self.encoded[:, parent, s], self.encoded[:, i, s]]
                    )
        path = next(p for p in planning["regret_paths"] if p["id"] == path_id)
        return out - sum(
            float((loss * pop).sum())
            for loss, pop in zip(v.comparator_trajectory_loss(comparator_id, path), q)
        )

    def safety_row(self, q, requirement):
        v = self.v
        mid = requirement["metric"]
        metric = v.metrics[mid]
        out = np.zeros(len(self.policies))
        i = v.node_index[metric["node"]]
        for s in range(v.s):
            mask = v.sid == s
            table = []
            for tid in v.template_ids:
                policy = tuple(tuple(tid for _ in range(v.s)) for _ in v.nodes)
                num, den = v.forms(policy, mid)
                form = (
                    num - requirement["threshold"] * den
                    if requirement["sense"] == "le"
                    else requirement["threshold"] * den - num
                )
                table.append(float((form[mask] * q[mask]).sum()))
            out += np.array(table)[self.encoded[:, i, s]]
        return out
