"""Reusable population and deployment primitives for the evaluation workbench.

All quantities are computed from the caller's evidence dictionary. This package
does not select an allocation, model attestation, search calibration, certify a
global deployment objective, or construct the required answer artifacts.

Public API
----------
Valuation(data)
    Holds node/template/metric metadata and forecast engines. A policy is a
    tuple of node rows in ``node_ids`` order, each containing template IDs in
    ascending stratum order. ``forms(policy, metric_id)`` returns numerator and
    denominator coefficient arrays of shape (N, 2), with benign/phishing labels.
    ``trajectory_loss(policy, path)`` and
    ``comparator_trajectory_loss(comparator_id, path)`` return (T, N, 2) linear
    coefficients; ``path`` is a planning.regret_paths entry. ``deployment_cost``
    returns the fixed whole-tree cost. These are unconditioned features.

TreeSpace(valuation)
    ``policies`` lists all structurally deployable trees; ``encoded`` holds
    template indices and ``fixed`` holds their fixed costs in the same order.
    ``risk_row(Q, path_id, comparator_id)`` evaluates paired loss for every tree.
    ``safety_row(q, requirement)`` evaluates every tree's signed requirement
    residual, with positive values denoting violations. These methods neither
    filter trees by statistical safety nor aggregate a lottery.

ForecastModel(data, forecast_id)
    Also available as ``valuation.engines[forecast_id]``. ``linear_max(c, key)``
    maximizes a supplied (N, 2) coefficient array over that forecast population.
    ``extreme(num, den, high, key)`` optimizes a supplied ratio; high=True means
    maximum and False means minimum. Each returns (value, attaining population).
    A fractional call requires its denominator to be positive over the set.

TrajectoryModel(data, engines)
    Also available as ``valuation.trajectory``. ``linear_max(c, key)`` accepts
    (T, N, 2) coefficients and returns (value, attaining trajectory), respecting
    forecast and drift constraints. Population coefficients are unnormalized
    masses. Keys are caller-owned cache identifiers: use a distinct key when
    the objective changes. Cache entries may be evicted, so keep needed outputs.

The package is optional; output validation does not depend on its use. It needs
only the NumPy/SciPy versions installed in the environment.
"""

from .features import Valuation
from .catalog import TreeSpace
from .population import ForecastModel, TrajectoryModel

__all__ = ["Valuation", "TreeSpace", "ForecastModel", "TrajectoryModel"]
