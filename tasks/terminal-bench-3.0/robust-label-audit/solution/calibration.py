"""Attaining bounds on a quadratic simplex using polar-form subdivision."""

import heapq
import itertools
import numpy as np

PAIRS = ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))
VERTICES = np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
SAMPLES = (
    (1.0, 0.0),
    (0.0, 1.0),
    (0.0, 0.0),
    (0.5, 0.5),
    (0.5, 0.0),
    (0.0, 0.5),
    (1 / 3, 1 / 3),
)


def evaluate(controls, alpha):
    a, b = alpha
    c = 1 - a - b
    return np.einsum(
        "i,i...->...", [a * a, b * b, c * c, 2 * a * b, 2 * a * c, 2 * b * c], controls
    )


def split(vertices, controls):
    i, j = max(
        ((0, 1), (0, 2), (1, 2)),
        key=lambda ij: np.sum((vertices[ij[0]] - vertices[ij[1]]) ** 2),
    )
    matrix = np.empty((3, 3) + controls.shape[1:])
    for value, (r, s) in zip(controls, PAIRS):
        matrix[r, s] = matrix[s, r] = value
    for replaced in (i, j):
        transform = np.eye(3)
        transform[replaced] = 0
        transform[replaced, i] = transform[replaced, j] = 0.5
        child = np.array(
            [
                np.einsum("i,j,ij...->...", transform[r], transform[s], matrix)
                for r, s in PAIRS
            ]
        )
        yield transform @ vertices, child


def minimum_quadratic(controls):
    aa, bb, cc, ab, ac, bc = np.asarray(controls)
    H = 2 * np.array(
        [[aa - 2 * ac + cc, ab - ac - bc + cc], [ab - ac - bc + cc, bb - 2 * bc + cc]]
    )
    g = 2 * np.array([ac - cc, bc - cc])
    candidates = list(SAMPLES[:3])
    for i, j in ((0, 1), (0, 2), (1, 2)):
        x, y = VERTICES[i], VERTICES[j]
        v = y - x
        curvature = float(v @ H @ v)
        if curvature > 0:
            t = -float(v @ (H @ x + g)) / curvature
            if 0 < t < 1:
                candidates.append(tuple(x + t * v))
    if np.linalg.det(H) != 0:
        x = np.linalg.solve(H, -g)
        if min(x) >= 0 and sum(x) <= 1:
            candidates.append(tuple(x))
    return min((float(evaluate(controls, x)), x) for x in candidates)


def maximize(controls, oracle, tolerance=2e-8, threshold=None):
    cache = {}
    serial = itertools.count()
    queue = []
    best = (-np.inf, None, None)

    def insert(vertices, cc):
        nonlocal best
        results = []
        for c in cc:
            key = c.tobytes()
            if key not in cache:
                cache[key] = oracle(c)
            results.append(cache[key])
        for x, result in zip(vertices, results[:3]):
            if result[0] > best[0]:
                best = (result[0], tuple(x), result[1])
        heapq.heappush(queue, (-max(v[0] for v in results), next(serial), vertices, cc))

    insert(VERTICES, controls)
    while queue:
        upper = max(best[0], -queue[0][0])
        if upper - best[0] <= tolerance or (
            threshold is not None and (upper <= threshold or best[0] > threshold)
        ):
            return (*best, upper)
        _, _, vv, cc = heapq.heappop(queue)
        for v, c in split(vv, cc):
            insert(v, c)
        if len(cache) > 16000:
            raise RuntimeError("simplex enclosure did not converge")
    raise RuntimeError("empty simplex search")


def maximize_cases(cases, denominators, oracle, tolerance=2e-8):
    serial = itertools.count()
    queue = []
    best = (-np.inf, None, None)

    def push(v, c, d, u, tag, exact=False):
        ub = float(np.max(u / d))
        if ub > best[0]:
            heapq.heappush(queue, (-ub, next(serial), v, c, d, u, tag, exact))

    for tag, c, u in cases:
        push(VERTICES, c, denominators, np.asarray(u), tag)
    while queue:
        upper = max(best[0], -queue[0][0])
        if upper - best[0] <= tolerance:
            return (*best, upper)
        _, _, v, c, d, u, tag, exact = heapq.heappop(queue)
        if not exact:
            results = [oracle(x) for x in c]
            u = np.array([x[0] for x in results])
            for j in range(3):
                val = u[j] / d[j]
                if val > best[0]:
                    best = (val, tuple(v[j]), (tag, results[j][1]))
            push(v, c, d, u, tag, True)
        else:
            cc, dd, uu = list(split(v, c)), list(split(v, d)), list(split(v, u))
            for j in range(2):
                push(cc[j][0], cc[j][1], dd[j][1], uu[j][1], tag)
    return (*best, best[0])
