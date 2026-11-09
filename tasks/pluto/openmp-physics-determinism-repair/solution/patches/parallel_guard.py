from __future__ import annotations

import os


def thread_buckets_requested(scenario: dict) -> int:
    env = os.environ.get("PHYSICS_THREAD_BUCKETS")
    if env is not None:
        return int(env)
    return int(scenario.get("thread_buckets", 4))


def parallel_ok(scenario: dict) -> bool:
    return thread_buckets_requested(scenario) >= 2


def effective_buckets(scenario: dict) -> int:
    return thread_buckets_requested(scenario)
