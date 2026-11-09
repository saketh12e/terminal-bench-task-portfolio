"""Independent objective reconstruction and exact two-dimensional cell minima."""

import numpy as np
from shapely.geometry import Point


def form(model, W, divisor):
    design = model["Zv"]
    offset = design @ W[:, 0] - model["yv"]
    slope = design @ W[:, 1:]
    weighted = model["vv"]
    # f(theta) = constant + linear.theta + 0.5 theta.Hessian.theta
    return (
        float(weighted @ (offset * offset)) / (2 * divisor),
        slope.T @ (weighted * offset) / divisor,
        slope.T @ (weighted[:, None] * slope) / divisor,
    )


def minimum_on_polygon(poly, constant, linear, hessian):
    vertices = np.asarray(poly.exterior.coords[:-1], float)
    candidates = list(vertices)
    for a, b in zip(vertices, np.roll(vertices, -1, axis=0)):
        d = b - a
        denominator = float(d @ hessian @ d)
        if denominator > 1e-24:
            u = -float(d @ (hessian @ a + linear)) / denominator
            if 0 < u < 1:
                candidates.append(a + u * d)
    stationary = np.linalg.lstsq(hessian, -linear, rcond=1e-13)[0]
    if np.max(np.abs(hessian @ stationary + linear)) < 1e-10 and poly.buffer(
        1e-12
    ).covers(Point(stationary)):
        candidates.append(stationary)
    return min(float(constant + linear @ x + 0.5 * x @ hessian @ x) for x in candidates)


def validation_value(models, weights):
    vals = []
    for name, p in models.items():
        if len(p["yv"]):
            err = p["Zv"] @ np.asarray(weights[name]) - p["yv"]
            vals.append(0.5 * float(p["vv"] @ (err * err)))
    return float(np.mean(vals))


def validation_derivative(models, weights, directions):
    vals = []
    for name, p in models.items():
        if len(p["yv"]):
            residual = p["Zv"] @ np.asarray(weights[name]) - p["yv"]
            variation = p["Zv"] @ np.asarray(directions[name])
            vals.append(float((p["vv"] * residual) @ variation))
    return float(np.mean(vals))
