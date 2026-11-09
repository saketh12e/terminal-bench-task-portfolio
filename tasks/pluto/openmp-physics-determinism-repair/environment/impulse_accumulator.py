from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed


def reduce_impulses(contacts: list[tuple[int, int, float]], thread_buckets: int) -> float:
    """Broken: completion order of thread pool makes sum non-deterministic."""
    if not contacts:
        return 0.0

    def _pair_sum(item: tuple[int, int, float]) -> float:
        return item[2]

    total = 0.0
    workers = max(1, int(thread_buckets))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_pair_sum, c) for c in contacts]
        for fut in as_completed(futures):
            total += fut.result()
    return total


def reduce_impulses_stable(contacts: list[tuple[int, int, float]], thread_buckets: int) -> float:
    if not contacts:
        return 0.0
    ordered = sorted(contacts, key=lambda c: (c[0], c[1]))
    total = 0.0
    comp = 0.0
    for _, _, imp in ordered:
        comp += imp
        total = comp
    _ = thread_buckets
    return total
