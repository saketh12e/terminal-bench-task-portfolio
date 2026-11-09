"""Reference: lift a feedback cycle, then intersect its graph with closure."""

import itertools
import numpy as np
from scipy.spatial import ConvexHull
from scipy.optimize import minimize
from shapely.geometry import Polygon, Point
from shapely.strtree import STRtree
from polygons import clip


def cut(vertices, halfspace):
    distances = np.c_[np.ones(len(vertices)), vertices] @ halfspace
    if distances.max() <= 2e-11:
        return vertices
    if distances.min() > 2e-11:
        return None
    hull = ConvexHull(vertices)
    edges = {
        tuple(sorted((int(t[i]), int(t[j]))))
        for t in hull.simplices
        for i, j in [(0, 1), (1, 2), (2, 0)]
    }
    out = [v for v, s in zip(vertices, distances) if s <= 1e-12]
    for i, j in edges:
        if distances[i] * distances[j] < 0:
            out.append(
                (distances[i] * vertices[j] - distances[j] * vertices[i])
                / (distances[i] - distances[j])
            )
    if len(out) < 4:
        return None
    _, unique = np.unique(np.round(out, 12), axis=0, return_index=True)
    result = np.asarray(out)[unique]
    if len(result) < 4:
        return None
    if np.linalg.matrix_rank(result[1:] - result[0], tol=1e-11) < 3:
        return None
    hull = ConvexHull(result)
    if hull.volume < 1e-14:
        return None
    return result[hull.vertices]


def halves(vertices):
    vertices = np.array(vertices)
    center = vertices.mean(axis=0)
    out = []
    for x, y in zip(vertices, np.roll(vertices, -1, axis=0)):
        normal = np.array([y[1] - x[1], x[0] - y[0]])
        if normal @ (center - x) > 0:
            normal = -normal
        length = np.linalg.norm(normal)
        if length < 1e-14:
            continue
        normal /= length
        out.append(np.r_[-normal @ x, normal])
    return out


def project(conditions, lift):
    """Eliminate the seed symbolically before constructing final polygon vertices."""
    polygon = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    for condition in conditions:
        line = condition @ lift
        size = np.linalg.norm(line[1:])
        if size < 1e-13:
            if line[0] > 1e-10:
                return None
            continue
        line /= size
        polygon = clip(polygon, line[1:], -line[0], tolerance=1e-13)
        if len(polygon) < 3:
            return None
    shape = Polygon(polygon).convex_hull
    if shape.geom_type != "Polygon" or shape.area <= 1e-18:
        return None
    return np.array(shape.exterior.coords[:-1])


def equilibria(data, models, atlases):
    names = list(data["fits"])
    local = {
        n: [(halves(c["vertices"]), np.array(c["weights"])) for c in atlases[n]]
        for n in names
    }
    # Homogeneous forms [constant, external drive, relaxation, initial blend].
    one, drive, relax, seed = np.eye(4)
    cube = np.array(list(itertools.product([0.0, 1.0], repeat=3)))
    states = [(cube, {0: seed}, {}, [-seed, seed - one])]
    out = []
    for index in [0, 3, 2, 1]:
        name = names[index]
        previous = (index - 1) % 4
        spec = data["feedback"][names[previous]]
        assert spec["source"] == name
        next_states = []
        for vertices, blends, weights, conditions in states:
            transform = np.array([one, blends[index], relax])
            for lines, local_weights in local[name]:
                restricted = vertices
                for line in lines:
                    restricted = cut(restricted, line @ transform)
                    if restricted is None:
                        break
                if restricted is None:
                    continue
                domain = conditions + [line @ transform for line in lines]
                law = local_weights @ transform
                all_weights = weights | {index: law}
                response = (
                    drive
                    + spec["offset"] * one
                    + np.array(spec["normal"]) @ models[name]["T"] @ law
                )
                for mode in [0, 1, 2]:
                    clipped = restricted
                    boundaries = (
                        [response]
                        if mode == 0
                        else [-response, response - one]
                        if mode == 1
                        else [one - response]
                    )
                    for boundary in boundaries:
                        clipped = cut(clipped, boundary)
                        if clipped is None:
                            break
                    if clipped is None:
                        continue
                    blend = 0 * one if mode == 0 else response if mode == 1 else one
                    if index != 1:
                        next_states.append(
                            (
                                clipped,
                                blends | {previous: blend},
                                all_weights,
                                domain + boundaries,
                            )
                        )
                        continue
                    closure = blend - seed
                    if abs(closure[3]) < 1e-8:
                        raise ValueError("singular feedback branch")
                    lift = np.vstack([np.eye(3), -closure[:3] / closure[3]])
                    polygon = project(domain + boundaries, lift)
                    if polygon is None:
                        continue
                    out.append(
                        dict(
                            vertices=polygon.tolist(),
                            blends=np.array(
                                [blends[j] @ lift for j in range(4)]
                            ).tolist(),
                            weights={
                                names[j]: (all_weights[j] @ lift).tolist()
                                for j in range(4)
                            },
                        )
                    )
        states = next_states
        print(
            name,
            "composition pieces",
            len(states),
            "equilibrium sheets",
            len(out),
            flush=True,
        )
    return out


def validation_form(model, weights):
    residual = model["Zv"] @ weights
    residual[:, 0] -= model["yv"]
    return residual.T @ (model["vv"][:, None] * residual) / 6


def select(models, cells):
    best = (np.inf, None, None)
    for cell in cells:
        vertices = np.array(cell["vertices"])
        Q = sum(
            validation_form(p, np.array(cell["weights"][n]))
            for n, p in models.items()
            if len(p["yv"])
        )
        lines = np.array(halves(vertices))

        def fun(t):
            return float(np.r_[1.0, t] @ Q @ np.r_[1.0, t])

        def jac(t):
            return 2 * (Q[1:, 0] + Q[1:, 1:] @ t)

        result = minimize(
            fun,
            vertices.mean(axis=0),
            jac=jac,
            method="SLSQP",
            constraints=[
                dict(
                    type="ineq",
                    fun=lambda t: -lines[:, 0] - lines[:, 1:] @ t,
                    jac=lambda t: -lines[:, 1:],
                )
            ],
            options=dict(ftol=1e-13, maxiter=100),
        )
        candidates = list(vertices)
        if np.max(lines[:, 0] + lines[:, 1:] @ result.x) <= 1e-9:
            candidates.append(result.x)
        # Independent endpoint candidates protect against a regional optimizer status failure.
        for x, y in zip(vertices, np.roll(vertices, -1, axis=0)):
            direction = y - x
            den = float(direction @ Q[1:, 1:] @ direction)
            if den > 1e-24:
                f = -float(direction @ (Q[1:, 1:] @ x + Q[1:, 0])) / den
                candidates.append(x + np.clip(f, 0, 1) * direction)
        theta = min(candidates, key=fun)
        if fun(theta) < best[0]:
            best = (fun(theta), theta, cell)
    value, theta, cell = best
    homogeneous = np.r_[1.0, theta]
    return dict(
        version=2,
        theta=theta.tolist(),
        value=value,
        blends=(np.array(cell["blends"]) @ homogeneous).tolist(),
        models={
            n: (np.array(W) @ homogeneous).tolist() for n, W in cell["weights"].items()
        },
    )


def responses(data, models, cells):
    shapes = [Polygon(c["vertices"]) for c in cells]
    tree = STRtree(shapes)
    result = {}
    for query in data["queries"]:
        theta, direction = np.array(query["theta"]), np.array(query["direction"])
        values = []
        signatures = []
        for idx in tree.query(Point(theta).buffer(4e-9)):
            cell = cells[idx]
            lines = np.array(halves(cell["vertices"]))
            residual = lines[:, 0] + lines[:, 1:] @ theta
            if residual.max() > 3e-9:
                continue
            incident = abs(residual) <= 3e-9
            if np.any(
                (lines[:, 1:] @ (direction / np.linalg.norm(direction)))[incident]
                > 1e-9
            ):
                continue
            t, d = np.r_[1.0, theta], np.r_[0.0, direction]
            U = np.array(cell["blends"])
            weights = {n: np.array(W) @ t for n, W in cell["weights"].items()}
            derivatives = {n: np.array(W) @ d for n, W in cell["weights"].items()}
            key = np.r_[U @ t, U @ d, *weights.values(), *derivatives.values()]
            if any(np.max(abs(key - prev)) < 1e-7 for prev in signatures):
                continue
            signatures.append(key)
            loss_derivative = np.mean(
                [
                    float(
                        (p["vv"] * (p["Zv"] @ weights[n] - p["yv"]))
                        @ (p["Zv"] @ derivatives[n])
                    )
                    for n, p in models.items()
                    if len(p["yv"])
                ]
            )
            values.append(
                dict(
                    blends=(U @ t).tolist(),
                    blend_directions=(U @ d).tolist(),
                    weights={n: w.tolist() for n, w in weights.items()},
                    directions={n: w.tolist() for n, w in derivatives.items()},
                    validation_direction=float(loss_derivative),
                )
            )
        if not values:
            raise ValueError(("no directional equilibrium", query))
        result[query["id"]] = values
    return dict(version=2, queries=result)
