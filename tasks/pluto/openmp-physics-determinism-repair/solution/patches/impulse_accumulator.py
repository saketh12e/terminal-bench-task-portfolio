from __future__ import annotations


def reduce_impulses(contacts: list[tuple[int, int, float]], thread_buckets: int) -> float:
    if not contacts:
        return 0.0
    ordered = sorted(contacts, key=lambda c: (c[0], c[1]))
    total = 0.0
    for _, _, imp in ordered:
        total += imp
    _ = thread_buckets
    return total
