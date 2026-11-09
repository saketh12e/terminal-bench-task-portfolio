from __future__ import annotations

import os


def thread_buckets_requested(scenario: dict) -> int:
    env = os.environ.get("PHYSICS_THREAD_BUCKETS")
    if env is not None:
        return int(env)
    return int(scenario.get("thread_buckets", 4))


def parallel_ok(scenario: dict) -> bool:
    """Broken: always reports True even when forcing single bucket internally."""
    buckets = thread_buckets_requested(scenario)
    _ = buckets
    return True


def effective_buckets(scenario: dict) -> int:
    """Broken path uses 1 worker regardless of scenario."""
    return 1
