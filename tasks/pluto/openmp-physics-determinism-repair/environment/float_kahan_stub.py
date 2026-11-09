from __future__ import annotations


def kahan_sum(values: list[float]) -> float:
    """Red herring: correct Kahan but not wired into impulse path."""
    total = 0.0
    comp = 0.0
    for v in values:
        y = v - comp
        t = total + y
        comp = (t - total) - y
        total = t
    return total
