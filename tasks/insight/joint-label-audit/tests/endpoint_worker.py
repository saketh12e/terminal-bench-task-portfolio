"""Evaluate independent sharp endpoints on the two assigned verifier CPUs."""

import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from lottery_audit import LotteryAudit

_AUDIT = None
_WITNESSES = None


def _initialize(problem, evaluation, witnesses):
    global _AUDIT, _WITNESSES
    # Spawn fresh numerical runtimes instead of forking an active LP/MIP runtime.
    _AUDIT = LotteryAudit(problem, evaluation)
    _WITNESSES = witnesses


def _endpoint(request):
    group, metric, side = request
    return (metric, group, side), _AUDIT.endpoint_errors(
        _WITNESSES, metric, group, side
    )


def endpoint_batch(problem, evaluation, witnesses, requests):
    """Return every independently certified endpoint; worker errors propagate."""
    with ProcessPoolExecutor(
        max_workers=2,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_initialize,
        initargs=(problem, evaluation, witnesses),
    ) as workers:
        return dict(workers.map(_endpoint, requests, chunksize=1))
