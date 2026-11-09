"""Independent full-label forecast and trajectory geometry for rollout evaluation."""

from __future__ import annotations

import json
import math
import os
import stat
from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.optimize import linprog

from linear_support import LinearSupport

FEAS_TOL = 1e-7
VALUE_TOL = 1e-6
GATE_EPS = 1e-9
MAX_TREES = 5_000_000
MAX_JSON = 1 << 20
MAX_NPZ = 32 << 20
MAX_NPZ_RAW = 64 << 20
CELL_FIELDS = ("stratum", "inc", "a", "b", "c", "u", "v")
SELECTOR_KEYS = CELL_FIELDS + ("label",)
MODELS = ("inc", "a", "b", "c")
KINDS = ("precision", "recall", "fpr", "loss_delta")
SIDES = ("lo", "hi")


class EvidenceError(ValueError):
    pass


class ArtifactError(ValueError):
    pass


class SolverError(RuntimeError):
    pass


def _bad_const(name):
    raise ValueError(f"non-finite constant {name}")


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def read_regular(path, limit, err=ArtifactError):
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise err(f"{path}: missing or unreadable ({exc.strerror})") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise err(f"{path}: must be a regular file")
    if st.st_size > limit:
        raise err(f"{path}: exceeds {limit} bytes")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise err(f"{path}: exceeds {limit} bytes")
    return raw


def parse_json(raw, where, err):
    try:
        return json.loads(
            raw.decode("utf-8"), parse_constant=_bad_const, object_pairs_hook=_pairs
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise err(f"{where}: invalid JSON ({exc})") from None


def is_num(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _need(obj, key, where):
    if not isinstance(obj, dict) or key not in obj:
        raise EvidenceError(f"{where}: missing {key!r}")
    return obj[key]


def _f(value, where):
    if not is_num(value):
        raise EvidenceError(f"{where}: finite number required")
    return float(value)


def _ids(items, where):
    ids = [_need(item, "id", f"{where}[{i}]") for i, item in enumerate(items)]
    if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
        raise EvidenceError(f"{where}: ids must be unique non-empty strings")
    return ids


def _vec(value, length, where):
    if not isinstance(value, list) or len(value) != length:
        raise EvidenceError(f"{where}: expected {length} numbers")
    return np.array([_f(x, where) for x in value])


def _strata(value, sidx, where):
    if (
        not isinstance(value, list)
        or not value
        or any(not is_int(x) or x not in sidx for x in value)
    ):
        raise EvidenceError(f"{where}: invalid stratum list")
    if len(value) != len(set(value)):
        raise EvidenceError(f"{where}: duplicate stratum")
    return np.array([sidx[x] for x in value], dtype=np.int64)


def _mask(selector, cols, n, where):
    if not isinstance(selector, dict):
        raise EvidenceError(f"{where}: selector must be an object")
    mask = np.ones((n, 2), dtype=bool)
    for key, allowed in selector.items():
        if (
            key not in SELECTOR_KEYS
            or not isinstance(allowed, list)
            or not all(is_int(x) for x in allowed)
        ):
            raise EvidenceError(f"{where}: invalid selector entry {key!r}")
        if key == "label":
            mask &= np.isin([0, 1], allowed)[None, :]
        else:
            mask &= np.isin(cols[key], allowed)[:, None]
    return mask


@dataclass(frozen=True)
class Metric:
    id: str
    forecast: str
    node: str
    mode: str
    kind: str
    scope: np.ndarray


@dataclass(frozen=True)
class Template:
    id: str
    deployments: dict
    deployment_costs: tuple


@dataclass(frozen=True)
class Comparator:
    id: str
    deployments: dict


@dataclass
class Problem:
    N: int
    S: int
    stratum_of: np.ndarray
    share: np.ndarray
    cols: dict
    fp: np.ndarray
    fn: np.ndarray
    switch: np.ndarray
    audits: list
    forecasts: dict
    modes: dict
    templates: dict
    template_ids: list
    architecture_constraints: tuple
    comparators: dict
    comparator_ids: list
    metrics: dict
    metric_ids: list
    requirements: tuple
    nodes: tuple
    node_ids: tuple
    node_index: dict
    node_map: dict
    edges: tuple
    reconfiguration_constraints: tuple
    fleet_constraints: tuple
    forecast_order: tuple
    period_weights: np.ndarray
    switch_weights: np.ndarray
    regret_paths: dict
    drift_constraints: tuple
    rollout_buckets: int = 16
    disclosure: dict | None = None

    def decision(self, policy, node_id, mode_id):
        out = np.empty(self.N, dtype=np.int64)
        for s, template_id in enumerate(policy[self.node_index[node_id]]):
            chosen = self.templates[template_id].deployments[mode_id]
            cells = self.stratum_of == s
            out[cells] = self.cols[chosen][cells]
        return out

    def comparator_decision(self, comparator_id, mode_id):
        out = np.empty(self.N, dtype=np.int64)
        for s, chosen in enumerate(
            self.comparators[comparator_id].deployments[mode_id]
        ):
            cells = self.stratum_of == s
            out[cells] = self.cols[chosen][cells]
        return out

    def forms(self, policy, metric_id):
        metric = self.metrics[metric_id]
        return coefficients(
            metric.kind,
            self.decision(policy, metric.node, metric.mode),
            self.cols["inc"],
            metric.scope,
            self.fp,
            self.fn,
        )

    def loss(self, policy, node_id, mode_id):
        dec = self.decision(policy, node_id, mode_id)
        coef = np.empty((self.N, 2))
        coef[:, 0] = self.fp * dec
        coef[:, 1] = self.fn * (1 - dec)
        return coef

    def comparator_loss(self, comparator_id, mode_id):
        dec = self.comparator_decision(comparator_id, mode_id)
        coef = np.empty((self.N, 2))
        coef[:, 0] = self.fp * dec
        coef[:, 1] = self.fn * (1 - dec)
        return coef

    def trajectory_loss(self, policy, path_id):
        path_nodes, out = self.regret_paths[path_id], []
        modes = [self.node_map[node]["mode"] for node in path_nodes]
        decisions = [
            self.decision(policy, node, mode) for node, mode in zip(path_nodes, modes)
        ]
        for period, (weight, node, mode) in enumerate(
            zip(self.period_weights, path_nodes, modes)
        ):
            coef = weight * self.loss(policy, node, mode)
            if period:
                penalty = (
                    self.switch_weights[period]
                    * self.switch
                    * np.abs(decisions[period] - decisions[period - 1])
                )
                coef = coef.copy()
                coef[:, 0] += penalty
                coef[:, 1] += penalty
            out.append(coef)
        return out

    def comparator_trajectory_loss(self, comparator_id, path_id):
        modes = [self.node_map[node]["mode"] for node in self.regret_paths[path_id]]
        out = []
        decisions = [self.comparator_decision(comparator_id, mode) for mode in modes]
        for period, (weight, mode) in enumerate(zip(self.period_weights, modes)):
            coef = weight * self.comparator_loss(comparator_id, mode)
            if period:
                penalty = (
                    self.switch_weights[period]
                    * self.switch
                    * np.abs(decisions[period] - decisions[period - 1])
                )
                coef = coef.copy()
                coef[:, 0] += penalty
                coef[:, 1] += penalty
            out.append(coef)
        return out

    def deployment_cost(self, policy):
        total = 0.0
        for node, node_policy in zip(self.nodes, policy):
            total += node["cost_weight"] * sum(
                self.templates[template_id].deployment_costs[s]
                for s, template_id in enumerate(node_policy)
            )
            if node["parent"] is not None:
                parent = policy[self.node_index[node["parent"]]]
                parent_mode = self.node_map[node["parent"]]["mode"]
                total += node["reconfiguration_weight"] * sum(
                    self.switch[self.stratum_of == s][0]
                    for s, (a, b) in enumerate(zip(parent, node_policy))
                    if self.templates[a].deployments[parent_mode]
                    != self.templates[b].deployments[node["mode"]]
                )
        return total


def coefficients(kind, dec, inc, scope, fp, fn):
    num, den = np.zeros((dec.size, 2)), np.zeros((dec.size, 2))
    selected = (dec == 1) * scope
    if kind == "precision":
        num[:, 1] = selected
        den[:, 0] = den[:, 1] = selected
    elif kind == "recall":
        num[:, 1] = selected
        den[:, 1] = scope
    elif kind == "fpr":
        num[:, 0] = selected
        den[:, 0] = scope
    elif kind == "loss_delta":
        change = dec.astype(float) - inc
        num[:, 0] = scope * fp * change
        num[:, 1] = -scope * fn * change
        den[:, 0] = den[:, 1] = scope
    else:
        raise EvidenceError(f"unsupported metric kind {kind!r}")
    return num, den


def parse_problem(data):
    if (
        not isinstance(data, dict)
        or data.get("version") != 9
        or isinstance(data.get("version"), bool)
    ):
        raise EvidenceError("evidence must be an object with version 9")
    list_fields = (
        "strata",
        "cells",
        "audits",
        "forecasts",
        "modes",
        "templates",
        "architecture_constraints",
        "comparators",
        "metrics",
    )
    for key in list_fields:
        if not isinstance(_need(data, key, "evidence"), list):
            raise EvidenceError(f"evidence.{key} must be a list")

    raw_sids = [_need(x, "id", "strata") for x in data["strata"]]
    if (
        not raw_sids
        or any(not is_int(x) for x in raw_sids)
        or len(raw_sids) != len(set(raw_sids))
    ):
        raise EvidenceError("strata ids must be unique integers")
    ordered_sids = sorted(raw_sids)
    sidx = {sid: i for i, sid in enumerate(ordered_sids)}
    S = len(sidx)
    fp_s, fn_s, switch_s = np.zeros(S), np.zeros(S), np.zeros(S)
    for row in data["strata"]:
        s = sidx[row["id"]]
        fp_s[s] = _f(_need(row, "fp_cost", "strata"), "fp_cost")
        fn_s[s] = _f(_need(row, "fn_cost", "strata"), "fn_cost")
        switch_s[s] = _f(_need(row, "switch_cost", "strata"), "switch_cost")
        if min(fp_s[s], fn_s[s], switch_s[s]) < 0:
            raise EvidenceError("stratum costs must be nonnegative")

    cells, N = data["cells"], len(data["cells"])
    if N == 0:
        raise EvidenceError("cells must not be empty")
    cols = {key: np.zeros(N, dtype=np.int64) for key in CELL_FIELDS}
    count = np.zeros(N)
    for i, cell in enumerate(cells):
        for key in CELL_FIELDS + ("count",):
            value = _need(cell, key, f"cells[{i}]")
            if not is_int(value):
                raise EvidenceError(f"cells[{i}].{key}: integer required")
            if key == "count":
                if value <= 0:
                    raise EvidenceError(f"cells[{i}].count must be positive")
                count[i] = value
            else:
                cols[key][i] = value
        if cols["stratum"][i] not in sidx:
            raise EvidenceError(f"cells[{i}]: unknown stratum")
    stratum_of = np.array([sidx[x] for x in cols["stratum"]], dtype=np.int64)
    total = np.bincount(stratum_of, weights=count, minlength=S)
    if np.any(total <= 0):
        raise EvidenceError("every stratum must contain cells")
    share = count / total[stratum_of]
    fp, fn, switch = fp_s[stratum_of], fn_s[stratum_of], switch_s[stratum_of]

    audits = []
    _ids(data["audits"], "audits")
    for i, audit in enumerate(data["audits"]):
        where = f"audits[{i}]"
        given = _mask(_need(audit, "given", where), cols, N, where)
        event = _mask(_need(audit, "event", where), cols, N, where)
        audits.append(
            (
                audit["id"],
                given,
                given & event,
                _f(_need(audit, "lower", where), where),
                _f(_need(audit, "upper", where), where),
                _f(_need(audit, "min_mass", where), where),
            )
        )

    forecasts = {}
    _ids(data["forecasts"], "forecasts")
    for i, forecast in enumerate(data["forecasts"]):
        where = f"forecasts[{i}]"
        groups = _need(forecast, "groups", where)
        if not isinstance(groups, list):
            raise EvidenceError(f"{where}.groups must be a list")
        forecasts[forecast["id"]] = {
            "nominal": _vec(_need(forecast, "nominal", where), S, where),
            "lower": _vec(_need(forecast, "lower", where), S, where),
            "upper": _vec(_need(forecast, "upper", where), S, where),
            "l1": _f(_need(forecast, "l1_budget", where), where),
            "groups": [
                (
                    _strata(_need(g, "strata", where), sidx, where),
                    _f(_need(g, "lower", where), where),
                    _f(_need(g, "upper", where), where),
                )
                for g in groups
            ],
        }

    modes = {}
    _ids(data["modes"], "modes")
    for i, mode in enumerate(data["modes"]):
        unavailable = _need(mode, "unavailable", f"modes[{i}]")
        if (
            not isinstance(unavailable, list)
            or len(unavailable) != len(set(unavailable))
            or any(x not in MODELS[1:] for x in unavailable)
        ):
            raise EvidenceError(f"modes[{i}].unavailable is invalid")
        modes[mode["id"]] = frozenset(unavailable)

    template_ids = _ids(data["templates"], "templates")
    templates = {}
    for i, template in enumerate(data["templates"]):
        where = f"templates[{i}]"
        deployments = _need(template, "deployments", where)
        if not isinstance(deployments, dict) or set(deployments) != set(modes):
            raise EvidenceError(
                f"{where}.deployments must contain exactly every outage mode"
            )
        parsed = {}
        for mode_id, model in deployments.items():
            if model not in MODELS:
                raise EvidenceError(f"{where}.deployments[{mode_id!r}] is invalid")
            if model in modes[mode_id]:
                raise EvidenceError(
                    f"{where}.deployments[{mode_id!r}] uses an unavailable model"
                )
            parsed[mode_id] = model
        costs = _vec(_need(template, "deployment_costs", where), S, where)
        if np.any(costs < 0):
            raise EvidenceError(f"{where}.deployment_costs must be nonnegative")
        templates[template["id"]] = Template(template["id"], parsed, tuple(costs))

    architecture_constraints = []
    _ids(data["architecture_constraints"], "architecture_constraints")
    for i, row in enumerate(data["architecture_constraints"]):
        where = f"architecture_constraints[{i}]"
        strata = tuple(_strata(_need(row, "strata", where), sidx, where))
        tids = _need(row, "templates", where)
        if (
            not isinstance(tids, list)
            or not tids
            or len(tids) != len(set(tids))
            or any(tid not in templates for tid in tids)
        ):
            raise EvidenceError(f"{where}.templates is invalid")
        lower, upper = (
            _f(_need(row, "lower", where), where),
            _f(_need(row, "upper", where), where),
        )
        if lower < 0 or upper < lower or upper > len(strata):
            raise EvidenceError(f"{where}: invalid bounds")
        nodes_raw = _need(row, "nodes", where)
        if (
            not isinstance(nodes_raw, list)
            or not nodes_raw
            or len(nodes_raw) != len(set(nodes_raw))
        ):
            raise EvidenceError(f"{where}.nodes is invalid")
        architecture_constraints.append(
            (row["id"], tuple(nodes_raw), strata, tuple(tids), lower, upper)
        )

    comparator_ids = _ids(data["comparators"], "comparators")
    comparators = {}
    for i, comparator in enumerate(data["comparators"]):
        where = f"comparators[{i}]"
        deployments = _need(comparator, "deployments", where)
        if not isinstance(deployments, dict) or set(deployments) != set(modes):
            raise EvidenceError(
                f"{where}.deployments must contain exactly every outage mode"
            )
        parsed = {}
        for mode_id, assignment in deployments.items():
            if (
                not isinstance(assignment, list)
                or len(assignment) != S
                or any(model not in MODELS for model in assignment)
            ):
                raise EvidenceError(f"{where}.deployments[{mode_id!r}] is invalid")
            if any(model in modes[mode_id] for model in assignment):
                raise EvidenceError(
                    f"{where}.deployments[{mode_id!r}] uses an unavailable model"
                )
            parsed[mode_id] = tuple(assignment)
        comparators[comparator["id"]] = Comparator(comparator["id"], parsed)

    metric_ids = _ids(data["metrics"], "metrics")
    metrics = {}
    for i, metric in enumerate(data["metrics"]):
        where = f"metrics[{i}]"
        fid, node, mode, kind = (
            _need(metric, "forecast", where),
            _need(metric, "node", where),
            _need(metric, "mode", where),
            _need(metric, "kind", where),
        )
        if fid not in forecasts or mode not in modes or kind not in KINDS:
            raise EvidenceError(f"{where}: unknown forecast, mode, or kind")
        scope = np.isin(
            stratum_of, _strata(_need(metric, "strata", where), sidx, where)
        ).astype(float)
        metrics[metric["id"]] = Metric(metric["id"], fid, node, mode, kind, scope)

    planning = _need(data, "planning", "evidence")
    requirements = []
    raw_requirements = _need(planning, "requirements", "planning")
    if not isinstance(raw_requirements, list) or not raw_requirements:
        raise EvidenceError("planning.requirements must be a non-empty list")
    for i, req in enumerate(raw_requirements):
        mid, sense = (
            _need(req, "metric", f"requirements[{i}]"),
            _need(req, "sense", f"requirements[{i}]"),
        )
        if mid not in metrics or sense not in ("le", "ge"):
            raise EvidenceError(f"requirements[{i}] is invalid")
        requirements.append(
            (
                mid,
                sense,
                _f(_need(req, "threshold", f"requirements[{i}]"), f"requirements[{i}]"),
            )
        )
    raw_nodes = _need(planning, "nodes", "planning")
    node_ids = _ids(raw_nodes, "planning.nodes")
    node_map = {row["id"]: row for row in raw_nodes}
    node_index = {node_id: i for i, node_id in enumerate(node_ids)}
    roots, edges, by_period = [], [], {}
    for i, node in enumerate(raw_nodes):
        where = f"planning.nodes[{i}]"
        period, fid, mode = (
            _need(node, "period", where),
            _need(node, "forecast", where),
            _need(node, "mode", where),
        )
        parent = _need(node, "parent", where)
        if (
            not is_int(period)
            or period < 0
            or fid not in forecasts
            or mode not in modes
        ):
            raise EvidenceError(f"{where}: invalid period, forecast, or mode")
        if parent is None:
            roots.append(node["id"])
        elif parent not in node_map:
            raise EvidenceError(f"{where}: unknown parent")
        else:
            edges.append((parent, node["id"]))
        node["cost_weight"] = _f(_need(node, "cost_weight", where), where)
        node["reconfiguration_weight"] = _f(
            _need(node, "reconfiguration_weight", where), where
        )
        by_period.setdefault(period, set()).add(fid)
    if (
        len(roots) != 1
        or sorted(by_period) != list(range(len(by_period)))
        or any(len(values) != 1 for values in by_period.values())
    ):
        raise EvidenceError("nodes must form one rooted, period-complete forecast tree")
    forecast_order = [next(iter(by_period[t])) for t in range(len(by_period))]
    if any(metric.node not in node_map for metric in metrics.values()):
        raise EvidenceError("metric references an unknown node")
    weights = _vec(
        _need(planning, "period_weights", "planning"),
        len(forecast_order),
        "planning.period_weights",
    )
    if np.any(weights <= 0) or abs(float(weights.sum()) - 1.0) > 1e-12:
        raise EvidenceError("planning.period_weights must be positive and sum to one")
    switch_weights = _vec(
        _need(planning, "switch_weights", "planning"),
        len(forecast_order),
        "planning.switch_weights",
    )
    if np.any(switch_weights < 0) or switch_weights[0] != 0:
        raise EvidenceError(
            "planning.switch_weights must be nonnegative and begin with zero"
        )
    raw_paths = _need(planning, "regret_paths", "planning")
    path_ids = _ids(raw_paths, "regret_paths")
    regret_paths = {}
    for i, path in enumerate(raw_paths):
        path_nodes = _need(path, "nodes", f"regret_paths[{i}]")
        if (
            not isinstance(path_nodes, list)
            or len(path_nodes) != len(forecast_order)
            or any(node not in node_map for node in path_nodes)
        ):
            raise EvidenceError(f"regret_paths[{i}].nodes is invalid")
        if any(
            node_map[node]["period"] != period for period, node in enumerate(path_nodes)
        ) or any(
            node_map[path_nodes[t]]["parent"] != path_nodes[t - 1]
            for t in range(1, len(path_nodes))
        ):
            raise EvidenceError(f"regret_paths[{i}] is not a root-to-leaf path")
        regret_paths[path_ids[i]] = tuple(path_nodes)
    raw_drift = _need(planning, "drift_constraints", "planning")
    _ids(raw_drift, "drift_constraints")
    drift_constraints = []
    for i, drift in enumerate(raw_drift):
        where = f"drift_constraints[{i}]"
        selector = _mask(_need(drift, "selector", where), cols, N, where).astype(float)
        limit = _f(_need(drift, "max_abs", where), where)
        if limit < 0:
            raise EvidenceError(f"{where}.max_abs must be nonnegative")
        drift_constraints.append((drift["id"], selector, limit))
    reconfiguration_constraints = []
    for row in _need(planning, "reconfiguration_constraints", "planning"):
        edge = (
            _need(row, "parent", "reconfiguration"),
            _need(row, "child", "reconfiguration"),
        )
        if edge not in edges:
            raise EvidenceError("reconfiguration constraint references a non-edge")
        reconfiguration_constraints.append(
            (
                row["id"],
                edge,
                tuple(
                    _strata(
                        _need(row, "strata", "reconfiguration"), sidx, "reconfiguration"
                    )
                ),
                _f(_need(row, "max_changes", "reconfiguration"), "reconfiguration"),
            )
        )
    fleet_constraints = []
    for row in _need(planning, "fleet_constraints", "planning"):
        tids = tuple(_need(row, "templates", "fleet"))
        nids = tuple(_need(row, "nodes", "fleet"))
        if any(t not in templates for t in tids) or any(
            n not in node_map for n in nids
        ):
            raise EvidenceError("fleet constraint references unknown ids")
        fleet_constraints.append(
            (
                row["id"],
                nids,
                tuple(_strata(_need(row, "strata", "fleet"), sidx, "fleet")),
                tids,
                _f(row["lower"], "fleet"),
                _f(row["upper"], "fleet"),
            )
        )
    for i, row in enumerate(architecture_constraints):
        if any(node not in node_map for node in row[1]):
            raise EvidenceError("architecture constraint references unknown node")
    result = Problem(
        N,
        S,
        stratum_of,
        share,
        cols,
        fp,
        fn,
        switch,
        audits,
        forecasts,
        modes,
        templates,
        template_ids,
        tuple(architecture_constraints),
        comparators,
        comparator_ids,
        metrics,
        metric_ids,
        tuple(requirements),
        tuple(raw_nodes),
        tuple(node_ids),
        node_index,
        node_map,
        tuple(edges),
        tuple(reconfiguration_constraints),
        tuple(fleet_constraints),
        tuple(forecast_order),
        weights,
        switch_weights,
        regret_paths,
        tuple(drift_constraints),
    )

    buckets = data["planning"].get("rollout_buckets")
    if not is_int(buckets) or not 1 <= buckets <= 1024:
        raise EvidenceError("rollout_buckets must be an integer from 1 to 1024")
    result.rollout_buckets = buckets
    result.disclosure = _need(data, "disclosure", "evidence")
    return result


def load_problem(path):
    return parse_problem(
        parse_json(read_regular(path, 64 << 20, EvidenceError), path, EvidenceError)
    )


def collect_ids(path):
    try:
        with open(path, "rb") as stream:
            data = json.load(stream)
        return [x["id"] for x in data["metrics"]], None
    except Exception as exc:  # noqa: BLE001
        return [], f"cannot read evidence: {type(exc).__name__}: {exc}"


def _solve(c, A_ub, b_ub, A_eq, b_eq, bounds):
    last = None
    for options in (
        {"primal_feasibility_tolerance": 1e-9, "dual_feasibility_tolerance": 1e-9},
        {},
    ):
        result = linprog(
            c,
            A_ub=A_ub,
            b_ub=b_ub,
            A_eq=A_eq,
            b_eq=b_eq,
            bounds=bounds,
            method="highs",
            options=options,
        )
        if result.status == 0:
            return result
        last = result
        if result.status == 2:
            break
    raise SolverError(f"LP status {last.status}: {last.message}")


def _support(engine, costs):
    try:
        if engine._support_solver is None:
            engine._support_solver = LinearSupport(
                engine.A_ub, engine.b_ub, engine.A_eq, engine.b_eq, engine.bounds
            )
        return engine._support_solver.solve(costs)
    except RuntimeError:
        # Retry cold on any numerical/status failure; never accept an incumbent.
        engine._support_solver = None
        return _solve(
            costs, engine.A_ub, engine.b_ub, engine.A_eq, engine.b_eq, engine.bounds
        ).x


def as_q(value, n):
    array = np.asarray(value)
    if array.dtype.kind not in "iuf" or array.shape != (n, 2):
        raise ValueError(
            f"expected real numeric shape ({n}, 2), got {array.dtype} {array.shape}"
        )
    array = array.astype(np.float64)
    if not np.isfinite(array).all():
        raise ValueError("non-finite values")
    return array


class Engine:
    def __init__(self, problem, forecast_id):
        self.p, self.fid, self.f = problem, forecast_id, problem.forecasts[forecast_id]
        self.nq, self.n = 2 * problem.N, 2 * problem.N + 2 * problem.S
        self._fractional, self._linear = {}, {}
        self._support_solver = None
        self._build()

    def _build(self):
        p, f, N, S, nq = self.p, self.f, self.p.N, self.p.S, self.nq
        W, T = nq, nq + S
        eqr, eqc, eqv, beq = [], [], [], []
        ubr, ubc, ubv, bub = [], [], [], []

        def row(rs, cs, vs, rhses, cols, vals, rhs):
            r = len(rhses)
            rs.extend([r] * len(cols))
            cs.extend(cols)
            vs.extend(vals)
            rhses.append(rhs)

        for s in range(S):
            cells = np.flatnonzero(p.stratum_of == s)
            qi = np.concatenate([2 * cells, 2 * cells + 1]).tolist()
            row(eqr, eqc, eqv, beq, [W + s] + qi, [1.0] + [-1.0] * len(qi), 0.0)
        for i in range(N):
            row(
                eqr,
                eqc,
                eqv,
                beq,
                [2 * i, 2 * i + 1, W + int(p.stratum_of[i])],
                [1.0, 1.0, -float(p.share[i])],
                0.0,
            )
        row(eqr, eqc, eqv, beq, list(range(W, W + S)), [1.0] * S, 1.0)
        for s in range(S):
            row(ubr, ubc, ubv, bub, [W + s, T + s], [1.0, -1.0], f["nominal"][s])
            row(ubr, ubc, ubv, bub, [W + s, T + s], [-1.0, -1.0], -f["nominal"][s])
        row(ubr, ubc, ubv, bub, list(range(T, T + S)), [1.0] * S, f["l1"])
        for idx, lo, hi in f["groups"]:
            wcols = (W + idx).tolist()
            row(ubr, ubc, ubv, bub, wcols, [1.0] * len(wcols), hi)
            row(ubr, ubc, ubv, bub, wcols, [-1.0] * len(wcols), -lo)
        for _, given, joint, lo, hi, minimum in p.audits:
            given, joint = given.ravel().astype(float), joint.ravel().astype(float)
            for coef, rhs in (
                (-given, -minimum),
                (lo * given - joint, 0.0),
                (joint - hi * given, 0.0),
            ):
                nz = np.flatnonzero(coef)
                row(ubr, ubc, ubv, bub, nz.tolist(), coef[nz].tolist(), rhs)
        self.A_eq = sparse.csr_matrix((eqv, (eqr, eqc)), shape=(len(beq), self.n))
        self.b_eq = np.array(beq)
        self.A_ub = sparse.csr_matrix((ubv, (ubr, ubc)), shape=(len(bub), self.n))
        self.b_ub = np.array(bub)
        self.bounds = np.vstack(
            [
                np.column_stack([np.zeros(nq), np.full(nq, np.inf)]),
                np.column_stack([f["lower"], f["upper"]]),
                np.column_stack([np.zeros(S), np.full(S, np.inf)]),
            ]
        )
        wl = sparse.hstack(
            [sparse.csr_matrix((S, nq)), -sparse.eye(S), sparse.csr_matrix((S, S))]
        )
        self.cc_ub = sparse.vstack(
            [
                sparse.hstack([self.A_ub, -self.b_ub[:, None]]),
                sparse.hstack([wl, f["lower"][:, None]]),
                sparse.hstack([-wl, -f["upper"][:, None]]),
            ]
        ).tocsr()
        self.cc_eq = sparse.hstack([self.A_eq, -self.b_eq[:, None]]).tocsr()

    def _lift(self, coef):
        out = np.zeros(self.n)
        out[: self.nq] = coef.ravel()
        return out

    def extremum(self, num, den, side, key):
        cache_key = (key, side)
        if cache_key not in self._fractional:
            a, d = self._lift(num), self._lift(den)
            objective = np.append(-a if side == "hi" else a, 0.0)
            A_eq = sparse.vstack(
                [self.cc_eq, sparse.csr_matrix(np.append(d, 0.0))]
            ).tocsr()
            b_eq = np.append(np.zeros(self.cc_eq.shape[0]), 1.0)
            bounds = (
                [(0, None)] * self.nq
                + [(None, None)] * self.p.S
                + [(0, None)] * (self.p.S + 1)
            )
            result = _solve(
                objective, self.cc_ub, np.zeros(self.cc_ub.shape[0]), A_eq, b_eq, bounds
            )
            tau = result.x[-1]
            if tau <= 0:
                raise SolverError(f"{key}: metric denominator can reach zero")
            z = result.x[:-1] / tau
            self._fractional[cache_key] = (
                float(a @ z) / float(d @ z),
                z[: self.nq].reshape(-1, 2),
            )
        return self._fractional[cache_key]

    def linear_max(self, coef, key):
        # Search callers retain selected witnesses; bound the transient LP cache.
        if len(self._linear) >= 256:
            self._linear.clear()
        if key not in self._linear:
            lifted = self._lift(coef)
            x = _support(self, -lifted)
            self._linear[key] = (
                float(lifted @ x),
                x[: self.nq].reshape(-1, 2),
            )
        return self._linear[key]

    def residuals(self, q):
        p, f = self.p, self.f
        q = as_q(q, p.N)
        rows = q.sum(axis=1)
        w = np.bincount(p.stratum_of, weights=rows, minlength=p.S)
        residual = {
            "nonnegativity": max(0.0, -float(q.min())),
            "total_mass": abs(float(q.sum()) - 1.0),
            "row_marginal": float(np.abs(rows - p.share * w[p.stratum_of]).max()),
            "weight_bounds": max(
                0.0, float(np.maximum(f["lower"] - w, w - f["upper"]).max())
            ),
            "l1_budget": max(0.0, float(np.abs(w - f["nominal"]).sum()) - f["l1"]),
            "group_bounds": 0.0,
            "audit_min_mass": 0.0,
            "audit_lower": 0.0,
            "audit_upper": 0.0,
        }
        for idx, lo, hi in f["groups"]:
            value = float(w[idx].sum())
            residual["group_bounds"] = max(
                residual["group_bounds"], lo - value, value - hi
            )
        for _, given, joint, lo, hi, minimum in p.audits:
            mass, event = float(q[given].sum()), float(q[joint].sum())
            residual["audit_min_mass"] = max(residual["audit_min_mass"], minimum - mass)
            residual["audit_lower"] = max(residual["audit_lower"], lo * mass - event)
            residual["audit_upper"] = max(residual["audit_upper"], event - hi * mass)
        return {key: float(value) for key, value in residual.items()}


class TrajectoryEngine:
    """Joint three-period population model with adjacent-period mass-drift limits."""

    def __init__(self, problem, engines):
        self.p = problem
        self.engines = [engines[fid] for fid in problem.forecast_order]
        self.offsets = np.cumsum([0] + [engine.n for engine in self.engines[:-1]])
        self.n = sum(engine.n for engine in self.engines)
        self.A_eq = sparse.block_diag(
            [engine.A_eq for engine in self.engines], format="csr"
        )
        self.b_eq = np.concatenate([engine.b_eq for engine in self.engines])
        base_ub = sparse.block_diag(
            [engine.A_ub for engine in self.engines], format="csr"
        )
        b_ub = list(np.concatenate([engine.b_ub for engine in self.engines]))
        coupling = []
        for _, selector, limit in problem.drift_constraints:
            coef = selector.ravel()
            for period in range(len(self.engines) - 1):
                row = np.zeros(self.n)
                left, right = self.offsets[period], self.offsets[period + 1]
                row[left : left + self.engines[period].nq] = -coef
                row[right : right + self.engines[period + 1].nq] = coef
                coupling.extend(
                    [
                        sparse.csr_matrix(row[None, :]),
                        sparse.csr_matrix((-row)[None, :]),
                    ]
                )
                b_ub.extend([limit, limit])
        self.A_ub = sparse.vstack([base_ub] + coupling, format="csr")
        self.b_ub = np.array(b_ub)
        self.bounds = np.vstack([engine.bounds for engine in self.engines])
        self._linear = {}
        self._support_solver = None

    def linear_max(self, qcoefs, key):
        # Search callers retain selected witnesses; bound the transient LP cache.
        if len(self._linear) >= 256:
            self._linear.clear()
        if key not in self._linear:
            objective = np.zeros(self.n)
            for period, (engine, qcoef) in enumerate(zip(self.engines, qcoefs)):
                start = self.offsets[period]
                objective[start : start + engine.nq] = qcoef.ravel()
            x = _support(self, -objective)
            populations = np.stack(
                [
                    x[start : start + engine.nq].reshape(-1, 2)
                    for start, engine in zip(self.offsets, self.engines)
                ]
            )
            self._linear[key] = (float(objective @ x), populations)
        return self._linear[key]

    def residuals(self, populations):
        value = np.asarray(populations)
        expected = (len(self.engines), self.p.N, 2)
        if (
            value.dtype.kind not in "iuf"
            or value.shape != expected
            or not np.isfinite(value).all()
        ):
            raise ValueError(
                f"expected finite real numeric trajectory shape {expected}"
            )
        residual = {}
        for period, (fid, engine) in enumerate(
            zip(self.p.forecast_order, self.engines)
        ):
            for name, amount in engine.residuals(value[period]).items():
                residual[f"{fid}:{name}"] = amount
        for name, selector, limit in self.p.drift_constraints:
            masses = np.array([(selector * q).sum() for q in value])
            residual[f"drift:{name}"] = max(
                0.0, float(np.abs(np.diff(masses)).max()) - limit
            )
        return residual
