"""Independent polyhedral closure of the certified local model network.

The verifier clips H-polyhedra by solving triples of boundary planes. Closure is
eliminated algebraically into two-dimensional halfspaces, rather than sampling
roots or relying on the submitted equilibrium cells to enumerate branches.
"""

from dataclasses import dataclass
from itertools import combinations, product
import numpy as np
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree
from selection_check import form, minimum_on_polygon, validation_derivative


@dataclass
class Sheet:
    polygon: Polygon
    blends: np.ndarray
    weights: dict


def _finite(value, shape):
    def valid(v):
        return (
            all(valid(x) for x in v)
            if isinstance(v, list)
            else type(v) in (int, float) and np.isfinite(v)
        )

    assert valid(value), "nonfinite or nonnumeric equilibrium coefficient"
    result = np.asarray(value, float)
    assert result.shape == shape and np.max(abs(result)) <= 1e8
    return result


def _lines(polygon):
    v = np.asarray(polygon.exterior.coords[:-1], float)
    center = np.mean(v, axis=0)
    edges = np.roll(v, -1, axis=0) - v
    keep = np.linalg.norm(edges, axis=1) > 1e-15
    v, edges = v[keep], edges[keep]
    n = np.column_stack((edges[:, 1], -edges[:, 0]))
    n /= np.linalg.norm(n, axis=1)[:, None]
    offsets = np.einsum("ij,ij->i", n, v)
    signs = np.where(n @ center > offsets, -1.0, 1.0)
    return np.column_stack((-offsets * signs, n * signs[:, None]))


def _clip2(vertices, row):
    if len(vertices) < 3:
        return np.empty((0, 2))
    distances = np.c_[np.ones(len(vertices)), vertices] @ row
    if max(distances) <= 2e-12:
        return vertices
    if min(distances) > 2e-12:
        return np.empty((0, 2))
    result = []
    for i, a in enumerate(vertices):
        j = (i + 1) % len(vertices)
        if distances[i] <= 0:
            result.append(a)
        if distances[i] * distances[j] < 0:
            ratio = distances[i] / (distances[i] - distances[j])
            result.append(a + ratio * (vertices[j] - a))
    return np.asarray(result, float).reshape(-1, 2)


def _restrict(state, new_row):
    planes, vertices = state
    length = np.linalg.norm(new_row[1:])
    if length < 1e-13:
        return state if new_row[0] <= 1e-10 else None
    new_row = new_row / length
    residual = np.c_[np.ones(len(vertices)), vertices] @ new_row
    if max(residual) <= 2e-11:
        return state
    if min(residual) > 2e-11:
        return None
    pairs = np.array(list(combinations(range(len(planes)), 2)), int)
    systems = np.empty((len(pairs), 3, 3))
    systems[:, :2] = planes[pairs, 1:]
    systems[:, 2] = new_row[1:]
    rhs = np.column_stack((-planes[pairs, 0], np.full(len(pairs), -new_row[0])))
    keep = abs(np.linalg.det(systems)) > 1e-11
    fresh = np.linalg.solve(systems[keep], rhs[keep, :, None])[..., 0]
    all_planes = np.vstack((planes, new_row))
    if len(fresh):
        fresh = fresh[
            np.max(np.c_[np.ones(len(fresh)), fresh] @ all_planes.T, axis=1) <= 2e-10
        ]
    kept = vertices[residual <= 2e-12]
    points = np.vstack((kept, fresh))
    if len(points) < 4:
        return None
    # Deduplication affects geometry only below the disclosed domain slack.
    _, ids = np.unique(np.round(points, 12), axis=0, return_index=True)
    points = points[ids]
    if len(points) < 4 or np.linalg.matrix_rank(points - points.mean(0), tol=1e-11) < 3:
        return None
    distances = abs(np.c_[np.ones(len(points)), points] @ all_planes.T)
    active = np.min(distances, axis=0) < 1e-8
    return all_planes[active], points


def _local_regions(cells):
    groups = {}
    for cell in cells:
        key = tuple(np.round(cell.weights.ravel(), 8))
        groups.setdefault(key, []).append(cell)
    output = []
    for members in groups.values():
        shape = unary_union([c.polygon for c in members])
        hull = shape.convex_hull
        if shape.buffer(3e-10).covers(hull):
            output.append((_lines(hull), members[0].weights))
        else:
            output.extend((_lines(c.polygon), c.weights) for c in members)
    return output


def reconstruct(data, models, certified):
    """Enumerate all cycle roots from complete independently KKT-certified local maps."""
    names = list(data["fits"])
    assert len(names) == 4
    for i, name in enumerate(names):
        assert data["feedback"][name]["source"] == names[(i + 1) % 4]
    local = {n: _local_regions(certified[n]) for n in names}
    planes = np.array(
        [
            [0, -1, 0, 0],
            [-1, 1, 0, 0],
            [0, 0, -1, 0],
            [-1, 0, 1, 0],
            [0, 0, 0, -1],
            [-1, 0, 0, 1],
        ],
        float,
    )
    vertices = np.array(list(product([0.0, 1.0], repeat=3)))
    constant, drive, relaxation, initial = np.eye(4)
    states = [((planes, vertices), {0: initial}, {})]
    result = []
    square = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    for i in [0, 3, 2, 1]:
        prev = (i - 1) % 4
        spec = data["feedback"][names[prev]]
        following = []
        for region, blends, weights in states:
            substitution = np.array([constant, blends[i], relaxation])
            for boundaries, local_weights in local[names[i]]:
                part = region
                for boundary in boundaries:
                    part = _restrict(part, boundary @ substitution)
                    if part is None:
                        break
                if part is None:
                    continue
                W = local_weights @ substitution
                laws = weights | {i: W}
                raw = (
                    drive
                    + spec["offset"] * constant
                    + np.asarray(spec["normal"]) @ models[names[i]].T @ W
                )
                for constraints, law in [
                    ([raw], 0 * constant),
                    ([-raw, raw - constant], raw),
                    ([constant - raw], constant),
                ]:
                    piece = part
                    for constraint in constraints:
                        piece = _restrict(piece, constraint)
                        if piece is None:
                            break
                    if piece is None:
                        continue
                    if i != 1:
                        following.append((piece, blends | {prev: law}, laws))
                        continue
                    residual = law - initial
                    assert abs(residual[3]) > 1e-10, "non-isolated feedback continuum"
                    transform = np.vstack((np.eye(3), -residual[:3] / residual[3]))
                    polygon = square.copy()
                    for boundary in piece[0] @ transform:
                        norm = np.linalg.norm(boundary[1:])
                        if norm > 1e-13:
                            boundary = boundary / norm
                        polygon = _clip2(polygon, boundary)
                        if len(polygon) < 3:
                            break
                    if len(polygon) < 3:
                        continue
                    shape = Polygon(polygon).convex_hull
                    if shape.geom_type != "Polygon" or shape.area < 1e-16:
                        continue
                    result.append(
                        Sheet(
                            shape,
                            np.array([blends[j] @ transform for j in range(4)]),
                            {names[j]: laws[j] @ transform for j in range(4)},
                        )
                    )
        states = following
    assert result, "empty feedback graph"
    return result


def parse_graph(raw, names):
    assert set(raw) == {"version", "cells"}
    assert isinstance(raw["cells"], list) and 1 <= len(raw["cells"]) <= 4096
    result = []
    for cell in raw["cells"]:
        assert isinstance(cell, dict) and set(cell) == {"vertices", "blends", "weights"}
        assert isinstance(cell["vertices"], list) and 3 <= len(cell["vertices"]) <= 32
        vertices = _finite(cell["vertices"], (len(cell["vertices"]), 2))
        assert np.min(vertices) >= -1e-9 and np.max(vertices) <= 1 + 1e-9
        poly = Polygon(vertices)
        assert (
            poly.is_valid
            and poly.area > 0
            and poly.buffer(1e-9).covers(poly.convex_hull)
        )
        assert isinstance(cell["weights"], dict) and set(cell["weights"]) == set(names)
        result.append(
            Sheet(
                poly,
                _finite(cell["blends"], (4, 3)),
                {n: _finite(cell["weights"][n], (6, 3)) for n in names},
            )
        )
    return result


def _close(x, y, tolerance):
    x, y = np.asarray(x), np.asarray(y)
    return np.max(abs(x - y)) <= tolerance * (1 + max(np.max(abs(x)), np.max(abs(y))))


def _covers_graph(left, right):
    shapes = [s.polygon for s in right]
    tree = STRtree(shapes)
    for index, first in enumerate(left):
        cover = []
        for j in tree.query(first.polygon.buffer(1e-9)):
            second = right[j]
            cross = first.polygon.intersection(second.polygon)
            if cross.is_empty or cross.area <= 0 or cross.geom_type != "Polygon":
                continue
            t = np.c_[
                np.ones(len(cross.exterior.coords)), np.asarray(cross.exterior.coords)
            ]
            if not _close(t @ first.blends.T, t @ second.blends.T, 1e-7):
                continue
            if not all(
                _close(t @ first.weights[n].T, t @ second.weights[n].T, 1e-7)
                for n in first.weights
            ):
                continue
            cover.append(cross)
        assert cover, f"incomplete or spurious equilibrium sheet {index}"
        gap = first.polygon.difference(unary_union(cover).buffer(1e-9))
        assert gap.is_empty or gap.area <= 1e-18, (
            f"incomplete or spurious equilibrium sheet {index}: uncovered area {gap.area:.3g}"
        )


def check_graph(raw, true, names):
    supplied = parse_graph(raw, names)
    _covers_graph(supplied, true)
    _covers_graph(true, supplied)
    return supplied


def matches_selection(sheets, theta, blends, weights):
    t = np.r_[1.0, theta]
    return any(
        s.polygon.buffer(1e-9).covers(Point(theta))
        and _close(s.blends @ t, blends, 1e-7)
        and all(_close(s.weights[n] @ t, weights[n], 1e-7) for n in weights)
        for s in sheets
    )


def optimum(models, sheets):
    names = [n for n, p in models.items() if len(p.yv)]
    best = np.inf
    for sheet in sheets:
        forms = [form(models[n], sheet.weights[n], len(names)) for n in names]
        c = sum(x[0] for x in forms)
        g = sum(x[1] for x in forms)
        H = sum(x[2] for x in forms)
        best = min(best, minimum_on_polygon(sheet.polygon, c, g, H))
    return best


def directional_bundle(models, sheets, query):
    theta = np.array(query["theta"])
    direction = np.array(query["direction"])
    unit = direction / np.linalg.norm(direction)
    t = np.r_[1.0, theta]
    d = np.r_[0.0, direction]
    result = []
    for sheet in sheets:
        if not sheet.polygon.buffer(4e-9).covers(Point(theta)):
            continue
        lines = _lines(sheet.polygon)
        res = lines[:, 0] + lines[:, 1:] @ theta
        if max(res) > 3e-9 or np.any((lines[:, 1:] @ unit)[abs(res) <= 3e-9] > 1e-9):
            continue
        w = {n: W @ t for n, W in sheet.weights.items()}
        dw = {n: W @ d for n, W in sheet.weights.items()}
        result.append(
            dict(
                blends=sheet.blends @ t,
                blend_directions=sheet.blends @ d,
                weights=w,
                directions=dw,
                validation_direction=np.array(validation_derivative(models, w, dw)),
            )
        )
    assert result, "no directional branch"
    return result


def matches_response(a, b):
    return (
        _close(np.asarray(a["blends"]), b["blends"], 1e-7)
        and _close(np.asarray(a["blend_directions"]), b["blend_directions"], 1e-5)
        and all(
            _close(np.asarray(a["weights"][n]), b["weights"][n], 1e-7)
            and _close(np.asarray(a["directions"][n]), b["directions"][n], 1e-5)
            for n in b["weights"]
        )
        and _close(
            np.asarray(a["validation_direction"]), b["validation_direction"], 1e-5
        )
    )
