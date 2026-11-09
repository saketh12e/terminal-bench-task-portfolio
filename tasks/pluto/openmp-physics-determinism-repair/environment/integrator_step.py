from __future__ import annotations

from typing import Any


def euler_step(bodies: list[dict[str, Any]], impulse_sum: float, dt: float = 0.004) -> None:
    """Broken: casts velocities to float32 before write-back."""
    scale = impulse_sum * dt
    for body in bodies:
        vx = float(body["vx"]) + scale * 0.001
        vy = float(body["vy"]) - scale * 0.0007
        body["x"] = float(body["x"]) + vx * dt
        body["y"] = float(body["y"]) + vy * dt
        body["vx"] = float(float32(vx))
        body["vy"] = float(float32(vy))


def float32(x: float) -> float:
    import struct

    return struct.unpack("f", struct.pack("f", x))[0]


def euler_step_stable(bodies: list[dict[str, Any]], impulse_sum: float, dt: float = 0.004) -> None:
    scale = impulse_sum * dt
    for body in bodies:
        vx = float(body["vx"]) + scale * 0.001
        vy = float(body["vy"]) - scale * 0.0007
        body["x"] = float(body["x"]) + vx * dt
        body["y"] = float(body["y"]) + vy * dt
        body["vx"] = vx
        body["vy"] = vy
