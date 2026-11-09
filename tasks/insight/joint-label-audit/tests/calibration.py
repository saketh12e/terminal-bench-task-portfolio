"""Independent power-basis bounds on a correlated two-coordinate calibration."""

import heapq
import itertools
import numpy as np

CORNERS = np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
PAIRS = ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))
SAMPLES = (
    (0.0, 0.0),
    (1.0, 0.0),
    (0.0, 1.0),
    (0.5, 0.0),
    (0.0, 0.5),
    (0.5, 0.5),
    (1 / 3, 1 / 3),
)


def power_coefficients(c):
    aa, bb, cc, ab, ac, bc = np.asarray(c)
    return np.array(
        [
            cc,
            2 * (ac - cc),
            2 * (bc - cc),
            aa - 2 * ac + cc,
            2 * (ab - ac - bc + cc),
            bb - 2 * bc + cc,
        ]
    )


def value(poly, xy):
    x, y = xy
    return (
        poly[0]
        + x * poly[1]
        + y * poly[2]
        + x * x * poly[3]
        + x * y * poly[4]
        + y * y * poly[5]
    )


def patch_controls(poly, triangle):
    values = [value(poly, p) for p in triangle]
    for i, j in PAIRS[3:]:
        x, y = triangle[i]
        dx, dy = triangle[j] - triangle[i]
        values.append(
            values[i]
            + 0.5
            * (
                dx * (poly[1] + 2 * x * poly[3] + y * poly[4])
                + dy * (poly[2] + x * poly[4] + 2 * y * poly[5])
            )
        )
    return np.array(values)


def children(triangle):
    a, b, c = triangle
    ab, ac, bc = (a + b) / 2, (a + c) / 2, (b + c) / 2
    return (
        np.array([a, ab, ac]),
        np.array([ab, b, bc]),
        np.array([ac, bc, c]),
        np.array([ab, bc, ac]),
    )


def minimum_probability(c):
    p = power_coefficients(c)
    points = list(SAMPLES[:3])
    for i, j in ((0, 1), (0, 2), (1, 2)):
        start, stop = CORNERS[i], CORNERS[j]
        f0, fm, f1 = (float(value(p, start + t * (stop - start))) for t in (0, 0.5, 1))
        quadratic = 2 * (f0 + f1 - 2 * fm)
        linear = f1 - f0 - quadratic
        if quadratic > 0:
            t = -linear / (2 * quadratic)
            if 0 < t < 1:
                points.append(tuple(start + t * (stop - start)))
    H = np.array([[2 * p[3], p[4]], [p[4], 2 * p[5]]])
    if np.linalg.matrix_rank(H) == 2:
        point = np.linalg.solve(H, -p[1:3])
        if min(point) >= 0 and sum(point) <= 1:
            points.append(tuple(point))
    return min((float(value(p, point)), point) for point in points)


def curve_maximum(controls, oracle, tolerance=5e-8, threshold=None):
    poly = power_coefficients(controls)
    queue = [(float("-inf"), 0, CORNERS)]
    counter = itertools.count(1)
    evaluated = {}
    best = (-np.inf, None, None)
    while queue:
        negative_bound, _, triangle = heapq.heappop(queue)
        bound = max(best[0], -negative_bound)
        if bound - best[0] <= tolerance or (
            threshold is not None and (bound <= threshold or best[0] > threshold)
        ):
            return (*best, bound)
        results = []
        for coeff in patch_controls(poly, triangle):
            key = coeff.tobytes()
            if key not in evaluated:
                evaluated[key] = oracle(coeff)
            results.append(evaluated[key])
        for point, result in zip(triangle, results):
            if result[0] > best[0]:
                best = (result[0], tuple(point), result[1])
        upper = max(r[0] for r in results)
        for child in children(triangle):
            heapq.heappush(queue, (-upper, next(counter), child))
        if len(evaluated) > 24000:
            raise ValueError("simplex bound did not converge")
    raise ValueError("empty calibration domain")


def response_maximum(cases, denominator, oracle, tolerance=5e-8):
    dpoly = power_coefficients(denominator)
    polynomials = {tag: power_coefficients(c) for tag, c, _ in cases}
    queue = []
    serial = itertools.count()
    best = (-np.inf, None, None)

    def push(tag, triangle, numerator_bounds):
        den = patch_controls(dpoly, triangle)
        bound = float(np.max(numerator_bounds / den))
        heapq.heappush(queue, (-bound, next(serial), tag, triangle))

    for tag, _, bounds in cases:
        push(tag, CORNERS, bounds)
    while queue:
        neg, _, tag, triangle = heapq.heappop(queue)
        upper = max(best[0], -neg)
        if upper - best[0] <= tolerance:
            return (*best, upper)
        c = patch_controls(polynomials[tag], triangle)
        d = patch_controls(dpoly, triangle)
        results = [oracle(coeff) for coeff in c]
        numerator = np.array([r[0] for r in results])
        for j in range(3):
            attained = float(numerator[j] / d[j])
            if attained > best[0]:
                best = (attained, tuple(triangle[j]), (tag, results[j][1]))
        # Support functions are convex: subdividing these upper controls remains sound.
        local_poly = power_coefficients(numerator)
        for child, local in zip(children(triangle), children(CORNERS)):
            push(tag, child, patch_controls(local_poly, local))
    return (*best, best[0])
