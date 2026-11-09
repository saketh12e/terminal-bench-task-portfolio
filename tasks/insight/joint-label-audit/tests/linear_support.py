"""Reuse a simplex basis for fixed population constraints and changing costs.

SciPy 1.17.1 is pinned by the verifier image. Its bundled HiGHS interface
avoids rebuilding and presolving the same polytope at every calibration node.
"""

import numpy as np
from scipy import sparse
from scipy.optimize._highspy import _core as highs


class LinearSupport:
    def __init__(self, A_ub, b_ub, A_eq, b_eq, bounds):
        self.matrix = sparse.vstack([A_ub, A_eq], format="csr")
        self.lower = np.concatenate([np.full(len(b_ub), -np.inf), b_eq])
        self.upper = np.concatenate([b_ub, b_eq])
        self.bounds = np.asarray(bounds, dtype=float)
        self.indices = np.arange(self.matrix.shape[1], dtype=np.int32)
        self.solver = highs._Highs()
        for key, value in (
            ("output_flag", False),
            ("solver", "simplex"),
            ("parallel", "off"),
            ("primal_feasibility_tolerance", 1e-9),
            ("dual_feasibility_tolerance", 1e-9),
        ):
            self._check(self.solver.setOptionValue(key, value))
        model = highs.HighsLp()
        model.num_row_, model.num_col_ = self.matrix.shape
        model.col_cost_ = np.zeros(model.num_col_)
        model.col_lower_, model.col_upper_ = self.bounds.T
        model.row_lower_, model.row_upper_ = self.lower, self.upper
        model.a_matrix_.format_ = highs.MatrixFormat.kRowwise
        model.a_matrix_.num_row_, model.a_matrix_.num_col_ = self.matrix.shape
        model.a_matrix_.start_ = self.matrix.indptr.astype(np.int32)
        model.a_matrix_.index_ = self.matrix.indices.astype(np.int32)
        model.a_matrix_.value_ = self.matrix.data
        self._check(self.solver.passModel(model))

    @staticmethod
    def _check(status):
        if status != highs.HighsStatus.kOk:
            raise RuntimeError(f"population LP operation failed: {status}")

    def solve(self, costs):
        self._check(self.solver.changeColsCost(len(costs), self.indices, costs))
        self._check(self.solver.run())
        if self.solver.getModelStatus() != highs.HighsModelStatus.kOptimal:
            raise RuntimeError("population LP did not prove optimality")
        info = self.solver.getInfo()
        x = np.asarray(self.solver.getSolution().col_value, dtype=float)
        activity = self.matrix @ x
        residual = max(
            float(np.max(self.lower - activity)),
            float(np.max(activity - self.upper)),
            float(np.max(self.bounds[:, 0] - x)),
            float(np.max(x - self.bounds[:, 1])),
            info.max_primal_infeasibility,
            info.max_dual_infeasibility,
        )
        if not np.isfinite(x).all() or not np.isfinite(residual) or residual > 1e-8:
            raise RuntimeError("population LP numerical residual exceeds tolerance")
        return x
