"""Whole-tree loss and conditional metric numerators, before randomization."""

import numpy as np
from .population import ForecastModel, TrajectoryModel


class Valuation:
    def __init__(self, data):
        self.data = data
        self.n = len(data["cells"])
        self.s = len(data["strata"])
        self.sid = np.array([cell["stratum"] for cell in data["cells"]])
        self.templates = {row["id"]: row for row in data["templates"]}
        self.template_ids = list(self.templates)
        self.nodes = data["planning"]["nodes"]
        self.node_ids = [row["id"] for row in self.nodes]
        self.node_index = {node_id: i for i, node_id in enumerate(self.node_ids)}
        self.node_map = {row["id"]: row for row in self.nodes}
        self.edges = [
            (row["parent"], row["id"])
            for row in self.nodes
            if row["parent"] is not None
        ]
        self.edge_index = {edge: i for i, edge in enumerate(self.edges)}
        self.comparators = {row["id"]: row for row in data["comparators"]}
        self.modes = {mode["id"] for mode in data["modes"]}
        self.metrics = {metric["id"]: metric for metric in data["metrics"]}
        self.models = {
            name: np.array([cell[name] for cell in data["cells"]])
            for name in ("inc", "a", "b", "c")
        }
        self.fp = np.array([data["strata"][s]["fp_cost"] for s in self.sid])
        self.fn = np.array([data["strata"][s]["fn_cost"] for s in self.sid])
        self.switch = np.array([data["strata"][s]["switch_cost"] for s in self.sid])
        self.engines = {
            f["id"]: ForecastModel(data, f["id"]) for f in data["forecasts"]
        }
        self.trajectory = TrajectoryModel(data, self.engines)

    def decision(self, policy, node_id, mode_id):
        out = np.empty(self.n, dtype=int)
        node_policy = policy[self.node_index[node_id]]
        for s, template_id in enumerate(node_policy):
            model = self.templates[template_id]["deployments"][mode_id]
            cells = self.sid == s
            out[cells] = self.models[model][cells]
        return out

    def comparator_decision(self, comparator_id, mode_id):
        row = self.comparators[comparator_id]
        out = np.empty(self.n, dtype=int)
        for s, model in enumerate(row["deployments"][mode_id]):
            cells = self.sid == s
            out[cells] = self.models[model][cells]
        return out

    def forms(self, policy, metric_id):
        metric = self.metrics[metric_id]
        dec = self.decision(policy, metric["node"], metric["mode"])
        inc = self.models["inc"]
        scope = np.isin(self.sid, metric["strata"]).astype(float)
        num, den = np.zeros((self.n, 2)), np.zeros((self.n, 2))
        selected = (dec == 1) * scope
        if metric["kind"] == "precision":
            num[:, 1] = selected
            den[:, 0] = den[:, 1] = selected
        elif metric["kind"] == "recall":
            num[:, 1] = selected
            den[:, 1] = scope
        elif metric["kind"] == "fpr":
            num[:, 0] = selected
            den[:, 0] = scope
        else:
            change = dec.astype(float) - inc
            num[:, 0] = scope * self.fp * change
            num[:, 1] = -scope * self.fn * change
            den[:, 0] = den[:, 1] = scope
        return num, den

    def loss(self, policy, node_id, mode_id):
        dec = self.decision(policy, node_id, mode_id)
        coef = np.empty((self.n, 2))
        coef[:, 0] = self.fp * dec
        coef[:, 1] = self.fn * (1 - dec)
        return coef

    def comparator_loss(self, comparator_id, mode_id):
        dec = self.comparator_decision(comparator_id, mode_id)
        coef = np.empty((self.n, 2))
        coef[:, 0] = self.fp * dec
        coef[:, 1] = self.fn * (1 - dec)
        return coef

    def trajectory_loss(self, policy, path):
        planning, out = self.data["planning"], []
        path_nodes = path["nodes"]
        modes = [self.node_map[node]["mode"] for node in path_nodes]
        decisions = [
            self.decision(policy, node, mode) for node, mode in zip(path_nodes, modes)
        ]
        for period, (weight, node, mode) in enumerate(
            zip(planning["period_weights"], path_nodes, modes)
        ):
            coef = weight * self.loss(policy, node, mode)
            if period:
                changed = np.abs(decisions[period] - decisions[period - 1])
                penalty = planning["switch_weights"][period] * self.switch * changed
                coef = coef.copy()
                coef[:, 0] += penalty
                coef[:, 1] += penalty
            out.append(coef)
        return out

    def comparator_trajectory_loss(self, comparator_id, path):
        planning, out = self.data["planning"], []
        modes = [self.node_map[node]["mode"] for node in path["nodes"]]
        decisions = [self.comparator_decision(comparator_id, mode) for mode in modes]
        for period, (weight, mode) in enumerate(zip(planning["period_weights"], modes)):
            coef = weight * self.comparator_loss(comparator_id, mode)
            if period:
                changed = np.abs(decisions[period] - decisions[period - 1])
                penalty = planning["switch_weights"][period] * self.switch * changed
                coef = coef.copy()
                coef[:, 0] += penalty
                coef[:, 1] += penalty
            out.append(coef)
        return out

    def deployment_cost(self, policy):
        total = 0.0
        for node, node_policy in zip(self.nodes, policy):
            total += node["cost_weight"] * sum(
                self.templates[template_id]["deployment_costs"][s]
                for s, template_id in enumerate(node_policy)
            )
            if node["parent"] is not None:
                parent_policy = policy[self.node_index[node["parent"]]]
                parent_mode = self.node_map[node["parent"]]["mode"]
                total += node["reconfiguration_weight"] * sum(
                    self.switch[self.sid == s][0]
                    for s, (a, b) in enumerate(zip(parent_policy, node_policy))
                    if self.templates[a]["deployments"][parent_mode]
                    != self.templates[b]["deployments"][node["mode"]]
                )
        return total
