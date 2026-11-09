"""Optional generic convex-polygon primitives; no task optimization is included."""

import numpy as np


def clip(vertices, normal, offset, tolerance=1e-12):
    if len(vertices) == 0:
        return np.zeros((0, 2))
    out = []
    for p, q in zip(vertices, np.roll(vertices, -1, axis=0)):
        a, b = normal @ p - offset, normal @ q - offset
        if a <= tolerance:
            out.append(p)
        if (a < -tolerance and b > tolerance) or (a > tolerance and b < -tolerance):
            out.append(p + (q - p) * a / (a - b))
    if not out:
        return np.zeros((0, 2))
    cleaned = [out[0]]
    for p in out[1:]:
        if np.linalg.norm(p - cleaned[-1]) > 1e-11:
            cleaned.append(p)
    if len(cleaned) > 1 and np.linalg.norm(cleaned[0] - cleaned[-1]) < 1e-11:
        cleaned.pop()
    return np.array(cleaned)


def area(vertices):
    if len(vertices) < 3:
        return 0.0
    following = np.roll(vertices, -1, axis=0)
    return (
        abs(
            float(
                (
                    vertices[:, 0] * following[:, 1] - vertices[:, 1] * following[:, 0]
                ).sum()
            )
        )
        / 2
    )
