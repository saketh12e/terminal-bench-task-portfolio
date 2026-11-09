"""Fail-closed validation of a submitted piecewise-affine lexicographic KKT atlas (version 2).

Each cell carries affine coefficient triples [c, da, db] (multiply t=[1, a, b]) for the six
normalized final weights W (6,3), per-stage inequality multipliers L_j (m,3) for the three
lexicographic stages and per-stage equality multipliers e_j (r_j,3), r_j = 1, 3, 5. Stage j is
certified by its KKT system at the final weights:
  H_j w + g0_j + a g1_j + A' lambda_j + F_j' nu_j = 0,  lambda_j >= 0,
  lambda_j * (b0 + b b1 - A w) = 0,  with F_j = [E; B_0; ...; B_{j-1}].
Primal feasibility A w <= b0 + b b1 and E w = 0 are shared. The earlier-stage projection rows of
F_j are tautologically fixed to the earlier optimum at the final w (which the earlier stages
certify), so only E w is required to vanish. Stationarity, feasibility and multiplier sign are
affine on a cell and certified at vertices; each complementarity product is a quadratic whose
extrema lie at vertices, edge critical points or an interior critical point, all of which are
evaluated. The positive-definite final Hessian makes the lexicographic solution unique, so
overlapping certified cells agree and need no pairwise check.

All tolerance scales depend only on trusted evidence:
  S_i = 1 + sum_j |A_ij| + |offset_i| + |relax_i|          primal, complementarity: 1e-8 S_i
  R_{j,k} = 1 + sum_l |H_j[k,l]| + |g0_j[k]| + |g1_j[k]| + sum_i |A_ik| + sum_r |F_j[r,k]|
                                                            stationarity: 1e-8 R_{j,k}
  equality |E w| <= 3e-8, lambda >= -1e-8, certificate coefficients |.| <= 1e8.
"""

from dataclasses import dataclass
import math

import numpy as np
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union
from shapely.validation import explain_validity

from model import NDIM, build_models

KKT_TOL = 1e-8
EQ_TOL = 3e-8
GEOM_SLACK = 1e-9  # vertex/domain slack, theta clamp, coverage buffer
LOOKUP_RADIUS = 3e-9  # a cell or edge within this distance of theta is incident
TANGENT_TOL = 1e-9  # admitted iff outward_normal . d/|d| <= this on every incident edge
PRED_TOL = 1e-7
DERIV_TOL = 1e-5
MAX_CELLS = 256
MAX_VERTS = 32
MAX_COEF = 1e8
ATLAS_VERSION = 2
NSTAGES = 3


class AtlasError(ValueError):
    pass


def _need(cond, msg):
    if not cond:
        raise AtlasError(msg)


def _num(v, what, bound):
    _need(
        isinstance(v, (int, float)) and not isinstance(v, bool), f"{what}: not a number"
    )
    f = float(v)
    _need(
        math.isfinite(f) and abs(f) <= bound,
        f"{what}: not a finite number with |value| <= {bound:g}",
    )
    return f


def _matrix(v, rows, cols, what, bound):
    _need(
        isinstance(v, list) and (rows is None or len(v) == rows),
        f"{what}: wrong length",
    )
    out = []
    for i, r in enumerate(v):
        _need(
            isinstance(r, list) and len(r) == cols, f"{what}[{i}]: need {cols} numbers"
        )
        out.append([_num(x, f"{what}[{i}]", bound) for x in r])
    return np.array(out, float).reshape(len(v), cols)


@dataclass(frozen=True)
class Cell:
    vertices: np.ndarray  # (k, 2), counter-clockwise
    weights: np.ndarray  # (6, 3) final lexicographic weights
    multipliers: np.ndarray  # (3, m, 3) per-stage inequality multipliers
    equality_multiplier: tuple  # per-stage arrays of shape (1, 3), (3, 3), (5, 3)
    polygon: Polygon
    normals: np.ndarray  # (e, 2) unit outward edge normals
    offsets: np.ndarray  # (e,)  cell = {x : normals @ x <= offsets}
    segments: np.ndarray  # (e, 2, 2) edge endpoints matching normals

    def eval(self, theta):
        return self.weights @ np.array([1.0, float(theta[0]), float(theta[1])])


class CellList(list):
    """List of Cell plus an (n, 4) bounding-box array for point location."""

    def __init__(self, cells):
        super().__init__(cells)
        self.bbox = np.array([c.polygon.bounds for c in cells], float).reshape(
            len(cells), 4
        )


@dataclass(frozen=True)
class ValidatedAtlas:
    models: dict
    fits: dict  # fit name -> CellList


@dataclass(frozen=True)
class _Scales:
    S: np.ndarray  # (m,)
    R: tuple  # per-stage (6,) stationarity scales


def _scales(mdl):
    S = 1.0 + np.abs(mdl.A).sum(axis=1) + np.abs(mdl.b0) + np.abs(mdl.b1)
    R = tuple(
        1.0
        + np.abs(st.H).sum(axis=1)
        + np.abs(st.g0)
        + np.abs(st.g1)
        + np.abs(mdl.A).sum(axis=0)
        + np.abs(st.F).sum(axis=0)
        for st in mdl.stages
    )
    return _Scales(S, R)


def _parse_cell(raw, mdl, where):
    m = len(mdl.b0)
    _need(
        isinstance(raw, dict)
        and set(raw) == {"vertices", "weights", "multipliers", "equality_multiplier"},
        f"{where}: bad keys",
    )
    v = raw["vertices"]
    _need(
        isinstance(v, list) and 3 <= len(v) <= MAX_VERTS,
        f"{where}: need 3..{MAX_VERTS} vertices",
    )
    V = _matrix(v, None, 2, f"{where}.vertices", 2.0)
    _need(
        bool(np.all(V >= -GEOM_SLACK) and np.all(V <= 1.0 + GEOM_SLACK)),
        f"{where}: vertex outside [0,1]^2 beyond {GEOM_SLACK:g}",
    )
    W = _matrix(raw["weights"], NDIM, 3, f"{where}.weights", MAX_COEF)
    Lraw, eraw = raw["multipliers"], raw["equality_multiplier"]
    _need(
        isinstance(Lraw, list) and len(Lraw) == NSTAGES,
        f"{where}.multipliers: need {NSTAGES} stage matrices",
    )
    _need(
        isinstance(eraw, list) and len(eraw) == NSTAGES,
        f"{where}.equality_multiplier: need {NSTAGES} stage matrices",
    )
    L = np.stack(
        [
            _matrix(Lraw[j], m, 3, f"{where}.multipliers[{j}]", MAX_COEF)
            for j in range(NSTAGES)
        ]
    ).reshape(NSTAGES, m, 3)
    e = tuple(
        _matrix(
            eraw[j],
            len(mdl.stages[j].F),
            3,
            f"{where}.equality_multiplier[{j}]",
            MAX_COEF,
        )
        for j in range(NSTAGES)
    )

    poly = Polygon(V)
    _need(poly.is_valid, f"{where}: invalid polygon ({explain_validity(poly)})")
    _need(poly.area > 0.0, f"{where}: polygon has no positive area")
    if not poly.exterior.is_ccw:
        V = V[::-1].copy()
        poly = Polygon(V)
    D = np.roll(V, -1, axis=0) - V
    lens = np.hypot(D[:, 0], D[:, 1])
    cross = D[:, 0] * np.roll(D[:, 1], -1) - D[:, 1] * np.roll(D[:, 0], -1)
    chord = np.hypot(*(D + np.roll(D, -1, axis=0)).T)
    _need(
        bool(np.all(cross >= -GEOM_SLACK * chord)),
        f"{where}: polygon is not convex",
    )
    keep = lens > 0.0
    N = np.stack([D[keep, 1], -D[keep, 0]], axis=1) / lens[keep, None]
    off = np.einsum("ij,ij->i", N, V[keep])
    seg = np.stack([V[keep], np.roll(V, -1, axis=0)[keep]], axis=1)
    return Cell(V, W, L, e, poly, N, off, seg)


def _check_identities(cell, mdl, sc, where):
    """Polynomial KKT identities, coefficientwise (a full-dimensional cell requires them)."""
    W = cell.weights
    m = len(mdl.b0)
    with np.errstate(all="ignore"):
        eqc = mdl.E @ W  # (1, 3)
        s = (
            np.column_stack([mdl.b0, np.zeros(m), mdl.b1]) - mdl.A @ W
        )  # slack coeffs (m, 3)
    _need(bool(np.isfinite(eqc).all()), f"{where}: non-finite KKT coefficient")
    _need(
        bool(np.all(np.abs(eqc) <= EQ_TOL)),
        f"{where}: equality coefficient {float(np.abs(eqc).max()):.3e}",
    )
    for j, st in enumerate(mdl.stages):
        L, e = cell.multipliers[j], cell.equality_multiplier[j]
        with np.errstate(all="ignore"):
            G = np.column_stack([st.g0, st.g1, np.zeros(NDIM)])
            stc = st.H @ W + G + mdl.A.T @ L + st.F.T @ e  # (6, 3)
            cc = np.column_stack(
                [
                    L[:, 0] * s[:, 0],
                    L[:, 0] * s[:, 1] + L[:, 1] * s[:, 0],
                    L[:, 0] * s[:, 2] + L[:, 2] * s[:, 0],
                    L[:, 1] * s[:, 1],
                    L[:, 1] * s[:, 2] + L[:, 2] * s[:, 1],
                    L[:, 2] * s[:, 2],
                ]
            )  # [1,a,b,a2,ab,b2]
        for arr in (stc, cc):
            _need(
                bool(np.isfinite(arr).all()),
                f"{where}: stage {j} non-finite KKT coefficient",
            )
        r = np.abs(stc) / sc.R[j][:, None]
        _need(
            bool(np.all(r <= KKT_TOL)),
            f"{where}: stage {j} stationarity coefficient {float(r.max()):.3e} x R_j",
        )
        if m:
            c = np.abs(cc) / sc.S[:, None]
            _need(
                bool(np.all(c <= KKT_TOL)),
                f"{where}: stage {j} complementarity coefficient {float(c.max()):.3e} x S_i",
            )


def _complementarity(cell, L, Lv, S, SC):
    """max |lambda_i * slack_i| over vertices, edge critical points and interior critical point."""
    m = len(L)
    dL = np.roll(Lv, -1, axis=1) - Lv
    dS = np.roll(S, -1, axis=1) - S
    c2, c1 = dL * dS, Lv * dS + S * dL
    t = np.where(c2 != 0.0, -c1 / np.where(c2 != 0.0, 2.0 * c2, 1.0), -1.0)
    inside = (t > 0.0) & (t < 1.0)
    te = np.where(inside, t, 0.0)
    q = np.maximum(
        np.abs(Lv * S),
        np.where(inside, np.abs((Lv + te * dL) * (S + te * dS)), 0.0),
    )
    q = q.max(axis=1) if q.size else np.zeros(m)
    # interior critical point of each product (saddle unless degenerate; evaluated anyway)
    for i in range(m):
        lam, s = L[i], SC[i]
        M = np.array(
            [
                [2 * lam[1] * s[1], lam[1] * s[2] + lam[2] * s[1]],
                [lam[1] * s[2] + lam[2] * s[1], 2 * lam[2] * s[2]],
            ]
        )
        if np.isfinite(M).all() and abs(np.linalg.det(M)) > 1e-300:
            th = np.linalg.solve(M, -(s[0] * lam[1:] + lam[0] * s[1:]))
            if (
                np.isfinite(th).all()
                and np.abs(th).max() <= 2.0
                and cell.polygon.covers(Point(th))
            ):
                p = np.array([1.0, th[0], th[1]])
                q[i] = max(q[i], abs(float(lam @ p) * float(s @ p)))
    return q


def _check_kkt(cell, mdl, sc, where):
    _check_identities(cell, mdl, sc, where)
    m = len(mdl.b0)
    with np.errstate(all="ignore"):
        V = cell.vertices
        P = np.column_stack([np.ones(len(V)), V])  # (k, 3)
        a, b = V[:, 0], V[:, 1]
        Wv = cell.weights @ P.T  # (6, k)
        eq = (mdl.E @ Wv)[0]
        S = mdl.b0[:, None] + mdl.b1[:, None] * b - mdl.A @ Wv  # slack (m, k)
        SC = np.column_stack(
            [
                mdl.b0 - mdl.A @ cell.weights[:, 0],
                -(mdl.A @ cell.weights[:, 1]),
                mdl.b1 - mdl.A @ cell.weights[:, 2],
            ]
        )
    for arr in (Wv, eq, S):
        _need(bool(np.isfinite(arr).all()), f"{where}: non-finite KKT residual")
    _need(
        bool(np.all(np.abs(eq) <= EQ_TOL)),
        f"{where}: equality residual {float(np.abs(eq).max()):.3e}",
    )
    if m:
        p = -S / sc.S[:, None]
        _need(
            bool(np.all(p <= KKT_TOL)),
            f"{where}: primal infeasible {float(p.max()):.3e} x S_i",
        )
    for j, st in enumerate(mdl.stages):
        L, e = cell.multipliers[j], cell.equality_multiplier[j]
        with np.errstate(all="ignore"):
            Lv = L @ P.T  # (m, k)
            ev = e @ P.T  # (r, k)
            stv = (
                st.H @ Wv
                + st.g0[:, None]
                + st.g1[:, None] * a
                + mdl.A.T @ Lv
                + st.F.T @ ev
            )
            q = _complementarity(cell, L, Lv, S, SC) if m else np.zeros(0)
        for arr in (stv, Lv, ev, q):
            _need(
                bool(np.isfinite(arr).all()),
                f"{where}: stage {j} non-finite KKT residual",
            )
        r = np.abs(stv) / sc.R[j][:, None]
        _need(
            bool(np.all(r <= KKT_TOL)),
            f"{where}: stage {j} stationarity residual {float(r.max()):.3e} x R_j",
        )
        if m == 0:
            continue
        _need(
            bool(np.all(Lv >= -KKT_TOL)),
            f"{where}: stage {j} negative multiplier {float(Lv.min()):.3e}",
        )
        c = q / sc.S
        _need(
            bool(np.all(c <= KKT_TOL)),
            f"{where}: stage {j} complementarity {float(c.max()):.3e} x S_i",
        )


def validate_atlas(data, atlas):
    """Return ValidatedAtlas(models, fits) or raise AtlasError / model.ModelDataError."""
    models = build_models(data)
    _need(
        isinstance(atlas, dict) and set(atlas) == {"version", "fits"},
        "atlas: keys must be version, fits",
    )
    _need(
        type(atlas["version"]) is int and atlas["version"] == ATLAS_VERSION,
        f"atlas: version must be integer {ATLAS_VERSION}",
    )
    fits = atlas["fits"]
    _need(
        isinstance(fits, dict) and set(fits) == set(models),
        "atlas: fits must match evidence fits exactly",
    )
    domain = box(0.0, 0.0, 1.0, 1.0)
    out = {}
    for name, mdl in models.items():
        raw = fits[name]
        _need(
            isinstance(raw, list) and 1 <= len(raw) <= MAX_CELLS,
            f"fits[{name}]: need 1..{MAX_CELLS} cells",
        )
        sc = _scales(mdl)
        cells = []
        for i, rc in enumerate(raw):
            cell = _parse_cell(rc, mdl, f"fits[{name}][{i}]")
            _check_kkt(cell, mdl, sc, f"fits[{name}][{i}]")
            cells.append(cell)
        gap = domain.difference(
            unary_union([c.polygon for c in cells]).buffer(GEOM_SLACK)
        )
        _need(
            gap.is_empty or gap.area <= 1e-18,
            f"fits[{name}]: cells leave [0,1]^2 uncovered (area {gap.area:.3e})",
        )
        out[name] = CellList(cells)
    return ValidatedAtlas(models, out)


def _theta(theta):
    th = np.asarray(theta, float).reshape(-1)
    _need(
        th.shape == (2,) and bool(np.isfinite(th).all()),
        "theta must be two finite numbers",
    )
    _need(
        bool(np.all(th >= -GEOM_SLACK) and np.all(th <= 1.0 + GEOM_SLACK)),
        "theta outside [0,1]^2",
    )
    return np.clip(th, 0.0, 1.0)


def _near(cells, th):
    bb = getattr(cells, "bbox", None)
    if bb is None:
        bb = np.array([c.polygon.bounds for c in cells], float).reshape(len(cells), 4)
    r = LOOKUP_RADIUS
    idx = np.nonzero(
        (bb[:, 0] - r <= th[0])
        & (th[0] <= bb[:, 2] + r)
        & (bb[:, 1] - r <= th[1])
        & (th[1] <= bb[:, 3] + r)
    )[0]
    pt = Point(th)
    return [cells[i] for i in idx if cells[i].polygon.distance(pt) <= r]


def _agree(vals, tol, what):
    ref = vals[0]
    s = 1.0 + max(float(np.abs(v).max()) for v in vals)
    for v in vals[1:]:
        _need(
            float(np.abs(v - ref).max()) <= tol * s, f"{what}: certified cells disagree"
        )
    return ref


def value_at(cells, theta):
    """Normalized weights (6,) at theta; every certified cell containing theta must agree."""
    th = _theta(theta)
    near = _near(cells, th)
    _need(bool(near), f"no certified cell contains theta={th.tolist()}")
    return _agree([c.eval(th) for c in near], PRED_TOL, "value_at")


def directional_at(cells, theta, d):
    """Right derivative lim_{t->0+} (w(theta+t d) - w(theta))/t, shape (6,).

    A cell is incident when its distance to theta is <= 3e-9; an edge is incident when its
    supporting line passes within 3e-9 of theta. The cell is admitted iff
    outward_normal . d/|d| <= 1e-9 on every incident edge. All admitted cells must agree within
    1e-5 scaled.
    """
    th = _theta(theta)
    dv = np.asarray(d, float).reshape(-1)
    _need(
        dv.shape == (2,) and bool(np.isfinite(dv).all()),
        "direction must be two finite numbers",
    )
    nd = float(np.hypot(dv[0], dv[1]))
    if nd == 0.0:
        return np.zeros(NDIM)
    u = dv / nd
    ok = []
    for c in _near(cells, th):
        act = np.abs(c.normals @ th - c.offsets) <= LOOKUP_RADIUS
        if np.all(c.normals[act] @ u <= TANGENT_TOL):
            ok.append(c.weights[:, 1:] @ dv)
    _need(
        bool(ok),
        f"no certified cell admits direction {dv.tolist()} at theta={th.tolist()}",
    )
    return _agree(ok, DERIV_TOL, "directional_at")
