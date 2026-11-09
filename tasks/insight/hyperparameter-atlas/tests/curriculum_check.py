"""Independent continuation graph, path integrals and resource-constrained optimum."""

from itertools import product
import numpy as np
from feedback_check import _lines, _close, _finite


def restrictions(sheets, x, y):
    """Intersect each complete graph sheet with a parameter segment algebraically."""
    transform = np.column_stack((np.r_[1.0, x], np.r_[0.0, np.asarray(y) - x]))
    arcs = []
    for sheet in sheets:
        inequalities = _lines(sheet.polygon) @ transform
        low, high = 0.0, 1.0
        for c, slope in inequalities:
            # Event coordinates use the same disclosed supporting-line incidence.
            if abs(c) <= 3e-9:
                c = 0.0
            if abs(c + slope) <= 3e-9:
                c = -slope
            if abs(slope) < 1e-13:
                if c > 3e-9:
                    high = -1
                    break
            elif slope > 0:
                high = min(high, -c / slope)
            else:
                low = max(low, -c / slope)
        if high - low > 1e-10:
            arcs.append(
                (
                    low,
                    high,
                    sheet.blends @ transform,
                    {n: W @ transform for n, W in sheet.weights.items()},
                )
            )
    return arcs


def integrals(models, U, weights, lo, hi, duration):
    moments = np.array([hi - lo, (hi * hi - lo * lo) / 2, (hi**3 - lo**3) / 3])
    loss = 0.0
    folds = [n for n, p in models.items() if len(p.yv)]
    for n in folds:
        p = models[n]
        residual = p.Zv @ weights[n]
        residual[:, 0] -= p.yv
        quadratic = np.array(
            [
                p.vv @ (residual[:, 0] ** 2),
                2 * p.vv @ (residual[:, 0] * residual[:, 1]),
                p.vv @ (residual[:, 1] ** 2),
            ]
        )
        loss += duration * float(quadratic @ moments) / (2 * len(folds))
    exposure = duration * float(np.mean(U, axis=0) @ moments[:2])
    energy = sum(
        float(np.sum((p.T @ weights[n][:, 1]) ** 2)) for n, p in models.items()
    )
    energy *= (hi - lo) / (duration * len(models))
    return np.array([loss, exposure, energy])


def phase_options(models, sheets, phase):
    """Enumerate continuous full paths; independent of submitted path pieces."""
    states = [(np.asarray(phase["initial"]), np.zeros(3))]
    for leg, (x, y) in enumerate(zip(phase["theta"], phase["theta"][1:])):
        arcs = restrictions(sheets, np.array(x), np.array(y))
        cuts = sorted([0.0, 1.0] + [v for arc in arcs for v in arc[:2]])
        knots = []
        for cut in cuts:
            if not knots or cut - knots[-1] > 1e-9:
                knots.append(cut)
        knots[0], knots[-1] = 0.0, 1.0
        for lo, hi in zip(knots, knots[1:]):
            mid = (lo + hi) / 2
            choices = []
            for left, right, U, W in arcs:
                if left - 1e-10 <= mid <= right + 1e-10:
                    if not any(_close(U, np.asarray(old[0]), 1e-9) for old in choices):
                        choices.append((U, W))
            following = []
            for previous, cost in states:
                for U, W in choices:
                    if _close(U @ [1, lo], previous, 1e-7):
                        end = U @ [1, hi]
                        total = cost + integrals(
                            models, U, W, lo, hi, phase["durations"][leg]
                        )
                        if not any(
                            _close(end, e, 1e-9) and np.max(abs(total - c)) < 1e-10
                            for e, c in following
                        ):
                            following.append((end, total))
            states = following
            assert states, "no complete curriculum continuation"
    return np.array([c for end, c in states if _close(end, phase["initial"], 1e-7)])


def global_minimum(options, budgets):
    """Meet-in-the-middle exhaustive discrete optimization, without a MIP solver."""
    split = len(options) // 2
    halves = []
    for group in (options[:split], options[split:]):
        values = np.array(
            [
                np.sum(items, axis=0) if items else np.zeros(3)
                for items in product(*group)
            ]
        )
        halves.append(values)
    right = halves[1]
    answer = np.inf
    for row in halves[0]:
        legal = np.all(right[:, 1:] + row[1:] <= np.asarray(budgets) + 1e-10, axis=1)
        if np.any(legal):
            answer = min(answer, row[0] + np.min(right[legal, 0]))
    assert np.isfinite(answer), "infeasible authored curriculum budgets"
    return float(answer)


def check_curriculum(raw, data, models, sheets):
    assert set(raw) == {"version", "phases", "totals"}
    phases = data["curriculum"]["phases"]
    assert isinstance(raw["phases"], dict) and set(raw["phases"]) == {
        p["id"] for p in phases
    }
    totals = np.zeros(3)
    for phase in phases:
        pieces = raw["phases"][phase["id"]]
        assert isinstance(pieces, list) and 1 <= len(pieces) <= 512
        previous = np.asarray(phase["initial"])
        previous_weights = None
        cursor = 0.0
        leg = 0
        phase_sum = np.zeros(3)
        expected = [
            restrictions(sheets, np.array(x), np.array(y))
            for x, y in zip(phase["theta"], phase["theta"][1:])
        ]
        for piece in pieces:
            assert isinstance(piece, dict) and set(piece) == {
                "leg",
                "span",
                "blends",
                "weights",
            }
            assert type(piece["leg"]) is int and piece["leg"] == leg
            lo, hi = _finite(piece["span"], (2,))
            assert abs(lo - cursor) <= 1e-9 and hi > lo and -1e-9 <= lo < hi <= 1 + 1e-9
            U = _finite(piece["blends"], (4, 2))
            assert isinstance(piece["weights"], dict) and set(piece["weights"]) == set(
                models
            )
            W = {n: _finite(piece["weights"][n], (6, 2)) for n in models}
            assert _close(U @ [1, lo], previous, 1e-7), "discontinuous blend path"
            if previous_weights is not None:
                assert all(
                    _close(W[n] @ [1, lo], previous_weights[n], 1e-7) for n in models
                ), "discontinuous model path"
            covered = []
            for left, right, V, Z in expected[leg]:
                a, b = max(lo, left), min(hi, right)
                if b <= a:
                    continue
                times = np.array([[1, a], [1, b]])
                if (
                    _close(U, V, 1e-7)
                    and all(_close(W[n], Z[n], 1e-7) for n in models)
                    and _close(times @ U.T, times @ V.T, 1e-7)
                    and all(
                        _close(times @ W[n].T, times @ Z[n].T, 1e-7) for n in models
                    )
                ):
                    covered.append((a, b))
            assert covered, "path leaves the equilibrium graph"
            reach = lo
            for a, b in sorted(covered):
                if a <= reach + 1e-9:
                    reach = max(reach, b)
            assert reach >= hi - 1e-9, "path leaves the equilibrium graph"
            phase_sum += integrals(models, U, W, lo, hi, phase["durations"][leg])
            previous = U @ [1, hi]
            previous_weights = {n: w @ [1, hi] for n, w in W.items()}
            cursor = hi
            if abs(hi - 1) <= 1e-9:
                leg += 1
                cursor = 0.0
        assert leg == len(phase["durations"]) and cursor == 0.0, "unfinished path"
        assert _close(previous, phase["initial"], 1e-7), (
            "phase does not return to its initial equilibrium"
        )
        totals += phase_sum
    reported = _finite(raw["totals"], (3,))
    assert _close(reported, totals, 1e-7), "incorrect integrated curriculum totals"
    budgets = np.asarray(data["curriculum"]["budgets"])
    assert np.all(totals[1:] <= budgets + 1e-7), "curriculum resource budget exceeded"
    options = [phase_options(models, sheets, p) for p in phases]
    best = global_minimum(options, budgets)
    assert totals[0] <= best + 1e-6, "curriculum is not globally optimal"
    return dict(
        totals=totals.tolist(), minimum=best, option_counts=[len(x) for x in options]
    )
