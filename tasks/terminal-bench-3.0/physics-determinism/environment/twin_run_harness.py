from __future__ import annotations


def digests_match(run_a: list[str], run_b: list[str]) -> bool:
    """Broken: only compares first and last frames."""
    if len(run_a) != len(run_b) or not run_a:
        return False
    return run_a[0] == run_b[0] and run_a[-1] == run_b[-1]


def digests_match_full(run_a: list[str], run_b: list[str]) -> bool:
    return run_a == run_b
