"""Attaining populations and a global finite-bank lower-bound certificate."""

import numpy as np


def descriptor(game, group, calibration, choices):
    records = game.data["disclosure"]["records"]
    return {
        "exposure": group,
        "calibration": calibration,
        "responses": {
            records[r]: {"path": p, "comparator": c}
            for r, (p, c) in zip(game.groups[group], choices)
        },
    }


def outputs(game, weights, risks, bank, lower):
    v = game.v
    regret = max(risks, key=lambda r: r[0])
    score = max(risks, key=lambda r: r[1])
    report = {
        "version": 9,
        "mixture": [],
        "bounds": {},
        "metric_calibrations": {},
        "worst_case_regret": regret[0],
        "selection_score": score[1],
        "regret_adversary": descriptor(game, *regret[2:5]),
        "score_adversary": descriptor(game, *score[2:5]),
        "certificate": {"lower_bound": lower, "regret": [], "safety": []},
    }
    for w, p in zip(weights, game.space.policies):
        if w > 0:
            report["mixture"].append(
                {
                    "count": int(round(w * game.data["planning"]["rollout_buckets"])),
                    "policy_tree": {n: list(row) for n, row in zip(v.node_ids, p)},
                }
            )
    arrays = {"selection__regret": regret[5], "selection__score": score[5]}
    rq = []
    sq = []
    for kind, _, _, item in bank:
        group, alpha, which, q = item
        if kind == "risk":
            report["certificate"]["regret"].append(
                descriptor(game, group, alpha, which)
            )
            rq.append(q)
        else:
            report["certificate"]["safety"].append(
                {"exposure": group, "calibration": alpha, "metric": which["metric"]}
            )
            sq.append(q)
    arrays["certificate__regret"] = np.array(rq).reshape(
        -1, len(v.trajectory.engines), v.n, 2
    )
    arrays["certificate__safety"] = np.array(sq).reshape(-1, v.n, 2)
    for group, records in game.groups.items():
        report["bounds"][group] = {}
        report["metric_calibrations"][group] = {}
        for mid, metric in v.metrics.items():
            report["bounds"][group][mid] = []
            report["metric_calibrations"][group][mid] = []
            for high, side in [(False, "lo"), (True, "hi")]:
                best = game.endpoint(weights, group, mid, high)
                report["bounds"][group][mid].append(best[0])
                report["metric_calibrations"][group][mid].append(best[1])
                arrays[group + "__" + mid + "__" + side] = best[2]
    return report, arrays
