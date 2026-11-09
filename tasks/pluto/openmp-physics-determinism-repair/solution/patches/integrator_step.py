from __future__ import annotations

from typing import Any


def euler_step(bodies: list[dict[str, Any]], impulse_sum: float, dt: float = 0.004) -> None:
    scale = impulse_sum * dt
    for body in bodies:
        vx = float(body["vx"]) + scale * 0.001
        vy = float(body["vy"]) - scale * 0.0007
        body["x"] = float(body["x"]) + vx * dt
        body["y"] = float(body["y"]) + vy * dt
        body["vx"] = vx
        body["vy"] = vy
