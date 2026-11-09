"""Independent verifier-side construction of the per-fit lexicographic training models.

Built only from the protected evidence rows; never imports public or solution code.
Normalized weights w = [3 standardized slopes, head0 offset, head1 offset, intercept].
Per fit (training rows only):
  mu = sum(c*x)/sum(c),  scale = sqrt(sum(c*(x-mu)**2)/sum(c) + scale_floor**2)
  z  = [(x-mu)/scale, head==0, head==1, 1]
  target(u) = (1-u)*y + u*teacher
  Feasible set P(b): E w = 0 with E = [0,0,0,1,1,0];  A w <= b0 + b*b1 with A = N @ T.
  Strict lexicographic priority (never a weighted mixture):
    stage 0: min 0.5*||B0 w - t0||^2 over P, B0 row h = weighted mean of z within head h
             (weights renormalized inside each head), t0 = the same means of target(u)
    stage 1: min 0.5*||B1 w - t1||^2 over the stage-0 optimal set, B1 row k =
             weighted_mean(z_k * z) for standardized feature k in {0, 1} (weights normalized
             over all training rows), t1 = weighted_mean(z_k * target(u))
    stage 2: min f(w; u) = 0.5/sum(c) * sum c*(z@w - target(u))**2 + 0.5*sum(ridge*w**2)
             over the stage-1 optimal set.
  Each stage j has gradient H_j w + g0_j + u*g1_j. Because a least-squares stage fixes its
  projection B_j w on its optimal set, stage j is the QP over P with the additional
  equalities B_k w = B_k w* (k < j); its KKT equality rows are F_j = [E; B_0; ...; B_{j-1}].
  The base (stage-2) H = Z'CZ/sumC + diag(ridge) is positive definite, so w* is unique;
  g0 = -Z'Cy/sumC,  g1 = -Z'C(teacher - y)/sumC.
  physical v = T w (raw slopes, head offsets, raw intercept).
Validation (folds only): Zv uses the fold's training mu/scale; targets are row y;
weights vv are the fold's validation weights normalized to sum 1.
"""

from dataclasses import dataclass, fields
import math

import numpy as np

NDIM = 6
E_ROW = np.array([[0.0, 0.0, 0.0, 1.0, 1.0, 0.0]])
_ROW_KEYS = {"id", "x", "head", "y", "teacher", "weight"}


class ModelDataError(ValueError):
    pass


def _need(cond, msg):
    if not cond:
        raise ModelDataError(msg)


def _num(v, what):
    _need(
        isinstance(v, (int, float)) and not isinstance(v, bool), f"{what}: not a number"
    )
    f = float(v)
    _need(math.isfinite(f), f"{what}: not finite")
    return f


@dataclass(frozen=True)
class Stage:
    """One lexicographic stage: gradient H w + g0 + a g1; KKT equality rows F."""

    H: np.ndarray  # (6, 6), positive semidefinite (definite for the final stage)
    g0: np.ndarray  # (6,)
    g1: np.ndarray  # (6,)
    F: np.ndarray  # (r, 6): E then earlier-stage projection rows; r = 1, 3, 5


@dataclass(frozen=True)
class FitModel:
    name: str
    H: np.ndarray  # base (final-stage) objective, retained for reference comparisons
    g0: np.ndarray
    g1: np.ndarray
    A: np.ndarray
    b0: np.ndarray
    b1: np.ndarray
    E: np.ndarray
    T: np.ndarray
    mu: np.ndarray
    scale: np.ndarray
    ridge: np.ndarray
    Zv: np.ndarray
    yv: np.ndarray
    vv: np.ndarray
    train_ids: tuple
    validation_ids: tuple
    min_eig: float
    B0: np.ndarray  # (2, 6) per-head weighted means of z
    B1: np.ndarray  # (2, 6) weighted means of z_k * z, k = 0, 1
    stages: tuple  # (Stage, Stage, Stage) in strict priority order

    def __getitem__(self, key):
        if key not in {f.name for f in fields(self)}:
            raise KeyError(key)
        return getattr(self, key)

    @property
    def is_fold(self):
        return self.vv.size > 0

    def grad(self, w, theta):
        return self.H @ np.asarray(w, float) + self.g0 + float(theta[0]) * self.g1

    def physical(self, w):
        return self.T @ np.asarray(w, float)

    def val_loss(self, w):
        """0.5 * normalized-weight validation MSE (no ridge); None for the refit."""
        if not self.is_fold:
            return None
        r = self.Zv @ np.asarray(w, float) - self.yv
        return 0.5 * float(self.vv @ (r * r))


def _rows(data):
    rows = data.get("rows")
    _need(isinstance(rows, list) and rows, "rows must be a non-empty list")
    out = {}
    for i, r in enumerate(rows):
        _need(isinstance(r, dict) and set(r) == _ROW_KEYS, f"rows[{i}]: bad keys")
        rid = r["id"]
        _need(
            isinstance(rid, (str, int)) and not isinstance(rid, bool),
            f"rows[{i}]: bad id",
        )
        _need(rid not in out, f"rows[{i}]: duplicate id {rid!r}")
        x = r["x"]
        _need(isinstance(x, list) and len(x) == 3, f"rows[{i}]: x must have 3 entries")
        head = r["head"]
        _need(
            head in (0, 1) and not isinstance(head, bool) and isinstance(head, int),
            f"rows[{i}]: head must be 0 or 1",
        )
        wt = _num(r["weight"], f"rows[{i}].weight")
        _need(wt > 0.0, f"rows[{i}]: weight must be positive")
        out[rid] = (
            np.array([_num(v, f"rows[{i}].x") for v in x]),
            head,
            _num(r["y"], f"rows[{i}].y"),
            _num(r["teacher"], f"rows[{i}].teacher"),
            wt,
        )
    return out


def _ids(lst, rows, what):
    _need(isinstance(lst, list), f"{what}: must be a list")
    for rid in lst:
        _need(
            isinstance(rid, (str, int)) and not isinstance(rid, bool) and rid in rows,
            f"{what}: unknown row id {rid!r}",
        )
    _need(len(set(lst)) == len(lst), f"{what}: duplicate row ids")
    return tuple(lst)


def _design(rows, ids, mu, scale):
    Z = np.empty((len(ids), NDIM))
    for k, rid in enumerate(ids):
        x, head, _, _, _ = rows[rid]
        Z[k, :3] = (x - mu) / scale
        Z[k, 3] = 1.0 if head == 0 else 0.0
        Z[k, 4] = 1.0 if head == 1 else 0.0
        Z[k, 5] = 1.0
    return Z


def build_models(data):
    _need(isinstance(data, dict), "evidence must be an object")
    rows = _rows(data)
    ridge = data.get("ridge")
    _need(isinstance(ridge, list) and len(ridge) == NDIM, "ridge must have 6 entries")
    ridge = np.array([_num(v, "ridge") for v in ridge])
    _need(bool(np.all(ridge > 0.0)), "ridge entries must be positive")
    floor = _num(data.get("scale_floor"), "scale_floor")
    _need(floor > 0.0, "scale_floor must be positive")
    ineq = data.get("raw_inequalities")
    _need(isinstance(ineq, list), "raw_inequalities must be a list")
    N, off, rel = [], [], []
    for j, c in enumerate(ineq):
        _need(
            isinstance(c, dict) and set(c) == {"normal", "offset", "relax"},
            f"raw_inequalities[{j}]: bad keys",
        )
        _need(
            isinstance(c["normal"], list) and len(c["normal"]) == NDIM,
            f"raw_inequalities[{j}]: normal must have 6 entries",
        )
        N.append([_num(v, f"raw_inequalities[{j}].normal") for v in c["normal"]])
        off.append(_num(c["offset"], f"raw_inequalities[{j}].offset"))
        rel.append(_num(c["relax"], f"raw_inequalities[{j}].relax"))
    N = np.array(N, float).reshape(len(ineq), NDIM)
    b0, b1 = np.array(off, float), np.array(rel, float)

    fits = data.get("fits")
    _need(isinstance(fits, dict) and fits, "fits must be a non-empty object")
    models = {}
    for name, spec in fits.items():
        _need(isinstance(name, str) and name, "fit names must be non-empty strings")
        _need(
            isinstance(spec, dict) and set(spec) == {"train", "validation"},
            f"fits[{name}]: bad keys",
        )
        tr = _ids(spec["train"], rows, f"fits[{name}].train")
        va = _ids(spec["validation"], rows, f"fits[{name}].validation")
        _need(len(tr) > 0, f"fits[{name}]: empty training set")
        _need(not set(tr) & set(va), f"fits[{name}]: train/validation overlap")

        X = np.array([rows[r][0] for r in tr])
        c = np.array([rows[r][4] for r in tr])
        y = np.array([rows[r][2] for r in tr])
        t = np.array([rows[r][3] for r in tr])
        heads = np.array([rows[r][1] for r in tr])
        sc = float(c.sum())
        mu = (c @ X) / sc
        var = (c @ (X - mu) ** 2) / sc
        scale = np.sqrt(var + floor * floor)
        Z = _design(rows, tr, mu, scale)
        CZ = Z * (c / sc)[:, None]
        H = Z.T @ CZ + np.diag(ridge)
        H = 0.5 * (H + H.T)
        g0 = -(CZ.T @ y)
        g1 = -(CZ.T @ (t - y))

        # Stage 0: per-head weighted means, weights renormalized within each head.
        C0 = np.zeros((2, len(tr)))
        for h in (0, 1):
            mask = heads == h
            _need(bool(mask.any()), f"fits[{name}]: no training rows for head {h}")
            C0[h, mask] = c[mask] / float(c[mask].sum())
        # Stage 1: feature-weighted means with weights normalized over all training rows.
        C1 = np.stack([(c / sc) * Z[:, 0], (c / sc) * Z[:, 1]])
        stage_rows = []
        for C in (C0, C1):
            Bj = C @ Z
            stage_rows.append(
                (Bj, Bj.T @ Bj, -(Bj.T @ (C @ y)), -(Bj.T @ (C @ (t - y))))
            )
        B0, B1 = stage_rows[0][0], stage_rows[1][0]
        stages = (
            Stage(
                0.5 * (stage_rows[0][1] + stage_rows[0][1].T),
                stage_rows[0][2],
                stage_rows[0][3],
                E_ROW.copy(),
            ),
            Stage(
                0.5 * (stage_rows[1][1] + stage_rows[1][1].T),
                stage_rows[1][2],
                stage_rows[1][3],
                np.vstack([E_ROW, B0]),
            ),
            Stage(H.copy(), g0.copy(), g1.copy(), np.vstack([E_ROW, B0, B1])),
        )

        T = np.eye(NDIM)
        T[0:3, 0:3] = np.diag(1.0 / scale)
        T[5, 0:3] = -mu / scale
        A = N @ T

        if va:
            Zv = _design(rows, va, mu, scale)
            yv = np.array([rows[r][2] for r in va])
            cv = np.array([rows[r][4] for r in va])
            vv = cv / cv.sum()
        else:
            Zv, yv, vv = np.empty((0, NDIM)), np.empty(0), np.empty(0)

        eig = float(np.linalg.eigvalsh(H).min())
        _need(
            math.isfinite(eig) and eig > 0.0,
            f"fits[{name}]: Hessian not positive definite",
        )
        stage_arrays = [a for s in stages for a in (s.H, s.g0, s.g1, s.F)]
        for arr in (H, g0, g1, A, T, Zv, vv, *stage_arrays):
            _need(
                bool(np.all(np.isfinite(arr))),
                f"fits[{name}]: non-finite model quantity",
            )
        models[name] = FitModel(
            name,
            H,
            g0,
            g1,
            A,
            b0.copy(),
            b1.copy(),
            E_ROW.copy(),
            T,
            mu,
            scale,
            ridge.copy(),
            Zv,
            yv,
            vv,
            tr,
            va,
            eig,
            B0,
            B1,
            stages,
        )
    return models
