"""Reference: budgeted closed curricula along prescribed hyperparameter routes.

Each leg of a phase route is intersected geometrically with every equilibrium
sheet.  The resulting arcs are cut at every interval endpoint, forming a layer
graph whose continuous traversals are enumerated from the phase's initial
blend.  Every surviving closed traversal carries its three physical-time
integrals, and one traversal per phase is chosen by a binary program that
minimizes total validation loss subject to the exposure and energy caps.
"""

import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds
from shapely.geometry import LineString, Polygon
from shapely.strtree import STRtree

INCIDENCE = 3e-9
MATCH = 1e-7
MERGE = 1e-10


def _supporting(vertices):
    """Outward unit supporting lines [c, n] with n @ t + c <= 0 inside."""
    vertices = np.asarray(vertices, float)
    center = vertices.mean(axis=0)
    rows = []
    for a, b in zip(vertices, np.roll(vertices, -1, axis=0)):
        normal = np.array([b[1] - a[1], a[0] - b[0]])
        size = np.linalg.norm(normal)
        if size < 1e-14:
            continue
        normal /= size
        if normal @ (center - a) > 0:
            normal = -normal
        rows.append(np.r_[-normal @ a, normal])
    return np.array(rows)


def _parameter(point, x, y):
    direction = y - x
    return float((np.asarray(point) - x) @ direction / (direction @ direction))


def _geometric_span(shape, lines, segment, x, y):
    """Parameter interval of a convex sheet along one leg from shapely geometry."""
    slopes = lines[:, 1:] @ (y - x)
    at_x = lines[:, 0] + lines[:, 1:] @ x
    at_y = lines[:, 0] + lines[:, 1:] @ y
    # A rounded route vertex within the incidence tolerance lies on that line.
    if np.any((np.abs(at_x) <= INCIDENCE) & (slopes > 1e-13)):
        return None
    if np.any((np.abs(at_y) <= INCIDENCE) & (slopes < -1e-13)):
        return None
    hit = shape.intersection(segment)
    if hit.is_empty:
        return None
    coords = []
    for part in getattr(hit, "geoms", [hit]):
        coords.extend(part.coords)
    values = [_parameter(c, x, y) for c in coords]
    low, high = min(values), max(values)
    if low < 1e-7 and float(np.max(at_x)) <= INCIDENCE:
        low = 0.0
    if high > 1 - 1e-7 and float(np.max(at_y)) <= INCIDENCE:
        high = 1.0
    if abs(low) < 1e-12:
        low = 0.0
    if abs(high - 1) < 1e-12:
        high = 1.0
    return max(low, 0.0), min(high, 1.0)


def _arcs(cells, shapes, lines, tree, x, y):
    segment = LineString([x, y])
    arcs = []
    for index in tree.query(segment.buffer(1e-8)):
        index = int(index)
        span = _geometric_span(shapes[index], lines[index], segment, x, y)
        if span is None or span[1] - span[0] <= MERGE:
            continue
        cell = cells[index]
        transform = np.array([[1.0, 0.0], [x[0], y[0] - x[0]], [x[1], y[1] - x[1]]])
        arcs.append(
            dict(
                span=span,
                blends=np.asarray(cell["blends"], float) @ transform,
                weights={
                    n: np.asarray(W, float) @ transform
                    for n, W in cell["weights"].items()
                },
            )
        )
    return arcs


def _value(arc, s):
    at = np.array([1.0, s])
    return np.r_[
        arc["blends"] @ at, *[arc["weights"][n] @ at for n in sorted(arc["weights"])]
    ]


def _close(x, y, tolerance=MATCH):
    x, y = np.asarray(x, float), np.asarray(y, float)
    scale = 1 + max(float(np.max(np.abs(x))), float(np.max(np.abs(y))))
    return float(np.max(np.abs(x - y))) <= tolerance * scale


def _same_affine(first, second, a, b):
    """Duplicate sheet copies agree coefficientwise and at both interval ends."""
    return (
        _close(first["blends"], second["blends"])
        and all(
            _close(first["weights"][n], second["weights"][n]) for n in first["weights"]
        )
        and all(_close(_value(first, s), _value(second, s)) for s in (a, b))
    )


def _piece_integrals(models, arc, a, b, duration):
    """Physical-time integrals of one affine piece on local parameter [a, b]."""
    folds = [n for n, p in models.items() if len(p["yv"])]

    def antiderivative(poly):
        primitive = np.polyint(poly)
        return np.polyval(primitive, b) - np.polyval(primitive, a)

    loss = 0.0
    for n in folds:
        p = models[n]
        W = arc["weights"][n]
        constant = p["Zv"] @ W[:, 0] - p["yv"]
        slope = p["Zv"] @ W[:, 1]
        # Weighted squared residual as a quadratic polynomial in s.
        poly = np.array(
            [
                p["vv"] @ slope**2,
                2 * p["vv"] @ (constant * slope),
                p["vv"] @ constant**2,
            ]
        )
        loss += 0.5 * antiderivative(poly) / len(folds)
    loss *= duration
    mean_blend = np.mean(arc["blends"], axis=0)
    exposure = duration * antiderivative(np.array([mean_blend[1], mean_blend[0]]))
    rates = [
        float(np.sum((models[n]["T"] @ arc["weights"][n][:, 1] / duration) ** 2))
        for n in models
    ]
    energy = float(np.mean(rates)) * duration * (b - a)
    return np.array([loss, exposure, energy])


def _pareto(options):
    kept = []
    for option in sorted(options, key=lambda o: tuple(o[1])):
        if any(np.all(other[1] <= option[1] + 1e-12) for other in kept):
            continue
        kept.append(option)
    return kept


def _phase_options(models, cells, shapes, lines, tree, phase):
    route = [np.asarray(v, float) for v in phase["theta"]]
    durations = [float(d) for d in phase["durations"]]
    initial = np.asarray(phase["initial"], float)
    legs = []
    for x, y in zip(route, route[1:]):
        arcs = _arcs(cells, shapes, lines, tree, x, y)
        points = sorted({0.0, 1.0, *[e for arc in arcs for e in arc["span"]]})
        breaks = [points[0]]
        for point in points[1:]:
            if point - breaks[-1] > MERGE:
                breaks.append(point)
        breaks[-1] = 1.0
        layers = []
        for a, b in zip(breaks, breaks[1:]):
            active = []
            for arc in arcs:
                left, right = arc["span"]
                if left <= a + 1e-9 and right >= b - 1e-9:
                    if not any(_same_affine(arc, kept, a, b) for kept in active):
                        active.append(arc)
            layers.append((a, b, active))
        legs.append(layers)

    memo = {}

    def extend(leg, layer, incoming):
        """All Pareto-useful closed continuations from a graph node."""
        if layer == len(legs[leg]):
            if leg + 1 < len(legs):
                return extend(leg + 1, 0, incoming)
            return (
                [((), np.zeros(3))]
                if np.max(np.abs(incoming[:4] - initial)) <= MATCH
                else []
            )
        key = (leg, layer, tuple(np.round(incoming, 8)))
        if key in memo:
            return memo[key]
        a, b, active = legs[leg][layer]
        found = []
        for arc in active:
            start = _value(arc, a)
            width = 4 if len(incoming) == 4 else len(start)
            if np.max(np.abs(start[:width] - incoming[:width])) > MATCH:
                continue
            piece = (leg, a, b, arc)
            cost = _piece_integrals(models, arc, a, b, durations[leg])
            for rest, total in extend(leg, layer + 1, _value(arc, b)):
                found.append(((piece,) + rest, total + cost))
        memo[key] = _pareto(found)
        return memo[key]

    options = extend(0, 0, initial)
    if not options:
        raise ValueError(("no closed curriculum continuation", phase["id"]))
    return options


def _serialize(pieces):
    out = []
    for leg, a, b, arc in pieces:
        if out and out[-1]["leg"] == leg and out[-1]["arc"] is arc:
            out[-1]["span"][1] = b
            continue
        out.append(dict(leg=leg, span=[a, b], arc=arc))
    return [
        dict(
            leg=int(p["leg"]),
            span=[float(p["span"][0]), float(p["span"][1])],
            blends=p["arc"]["blends"].tolist(),
            weights={n: W.tolist() for n, W in p["arc"]["weights"].items()},
        )
        for p in out
    ]


def _index(cells):
    shapes = [Polygon(c["vertices"]) for c in cells]
    lines = [_supporting(c["vertices"]) for c in cells]
    return shapes, lines, STRtree([s.buffer(1e-8) for s in shapes])


def phase_options(data, models, cells):
    """Per phase, every retained closed continuation as (pieces, [loss, exposure, energy])."""
    shapes, lines, tree = _index(cells)
    return {
        phase["id"]: [
            (_serialize(pieces), total.tolist())
            for pieces, total in _phase_options(
                models, cells, shapes, lines, tree, phase
            )
        ]
        for phase in data["curriculum"]["phases"]
    }


def solve_curriculum(data, models, cells):
    shapes, lines, tree = _index(cells)
    spec = data["curriculum"]
    phases = spec["phases"]
    options = [_phase_options(models, cells, shapes, lines, tree, p) for p in phases]
    for phase, found in zip(phases, options):
        print("curriculum", phase["id"], "closed continuations", len(found), flush=True)

    sizes = [len(o) for o in options]
    offsets = np.cumsum([0] + sizes)
    costs = np.array([total for found in options for _, total in found])
    assignment = np.zeros((len(phases), offsets[-1]))
    for i in range(len(phases)):
        assignment[i, offsets[i] : offsets[i + 1]] = 1
    budgets = np.asarray(spec["budgets"], float)
    result = milp(
        c=costs[:, 0],
        integrality=np.ones(offsets[-1]),
        bounds=Bounds(0, 1),
        constraints=[
            LinearConstraint(assignment, 1, 1),
            LinearConstraint(costs[:, 1:].T, -np.inf, budgets),
        ],
        options=dict(mip_rel_gap=0.0),
    )
    if result.status != 0 or result.x is None:
        raise ValueError(("infeasible curriculum budgets", result.message))
    chosen = np.round(result.x).astype(int)
    out, totals = {}, np.zeros(3)
    for i, phase in enumerate(phases):
        pick = int(np.flatnonzero(chosen[offsets[i] : offsets[i + 1]])[0])
        pieces, total = options[i][pick]
        serialized = _serialize(pieces)
        if len(serialized) > 512:
            raise ValueError(("too many curriculum pieces", phase["id"]))
        out[phase["id"]] = serialized
        totals += total
    return dict(version=2, phases=out, totals=totals.tolist())
