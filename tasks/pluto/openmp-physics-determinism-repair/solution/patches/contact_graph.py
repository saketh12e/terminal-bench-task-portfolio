from __future__ import annotations

import random
from typing import Any


def gather_contacts(bodies: list[dict[str, Any]], frame_idx: int, seed: int) -> list[tuple[int, int, float]]:
    contacts: list[tuple[int, int, float]] = []
    rng = random.Random(seed + frame_idx * 17)
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            dx = bodies[i]["x"] - bodies[j]["x"]
            dy = bodies[i]["y"] - bodies[j]["y"]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 2.5:
                impulse = rng.uniform(0.01, 0.08) * (2.5 - dist)
                contacts.append((i, j, impulse))
    contacts.sort(key=lambda c: (c[0], c[1]))
    return contacts
