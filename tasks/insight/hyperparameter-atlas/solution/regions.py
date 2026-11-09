"""Reference lexicographic active-face and stagewise dual-cone construction."""

import itertools
import numpy as np
from scipy.linalg import null_space
from shapely.geometry import Polygon
from polygons import clip, area


def lex_candidates(p, HH, GG):
    """Solve each priority only along directions preserving all earlier optima."""
    A = p["A"]
    m = len(A)
    rhs0 = np.column_stack([p["b0"], np.zeros(m), p["b1"]])
    seen = set()
    for k in range(6):
        for ids in itertools.combinations(range(m), k):
            C = np.vstack([p["E"], A[list(ids)]])
            N = null_space(C, rcond=1e-10)
            if C.shape[0] + N.shape[1] != 6:
                continue
            W = np.linalg.lstsq(
                C, np.vstack([np.zeros((1, 3)), rhs0[list(ids)]]), rcond=1e-11
            )[0]
            for H, G in zip(HH, GG):
                if not N.shape[1]:
                    break
                Q = N.T @ H @ N
                ev, U = np.linalg.eigh(Q)
                pos = ev > 1e-9
                W += (
                    N
                    @ U[:, pos]
                    @ ((U[:, pos].T @ (-N.T @ (H @ W + G))) / ev[pos, None])
                )
                N = N @ U[:, ~pos]
            key = tuple(np.round(W.ravel(), 8))
            if key in seen:
                continue
            seen.add(key)
            slack = rhs0 - A @ W
            poly = np.array([[0.0, 0.0], [1, 0], [1, 1], [0, 1]])
            for s in slack:
                if np.linalg.norm(s[1:]) < 1e-9:
                    if s[0] < -1e-8:
                        poly = []
                        break
                else:
                    poly = clip(poly, -s[1:], s[0])
                if len(poly) < 3:
                    break
            if len(poly) >= 3 and area(poly) > 1e-12:
                yield W, poly, slack


def dual_regions(p, W, poly, slack, H, G, F):
    """Cover each normal cone after removing the preceding summary equalities."""
    N = null_space(F, rcond=1e-10)
    R = -N.T @ (H @ W + G)
    act = np.where(np.max(abs(slack), axis=1) < 1e-8)[0]
    m = len(p["A"])
    r = N.shape[1]
    out = []
    for k in range(min(r, len(act)) + 1):
        for ss in itertools.combinations(act, k):
            M = N.T @ p["A"][list(ss)].T
            if k:
                if np.linalg.matrix_rank(M, tol=1e-9) < k:
                    continue
                L0 = np.linalg.lstsq(M, R, rcond=1e-10)[0]
                if abs(M @ L0 - R).max() > 1e-8:
                    continue
            else:
                if abs(R).max() > 1e-8:
                    continue
                L0 = np.zeros((0, 3))
            sub = np.array(poly)
            ok = True
            for q in L0:
                if np.linalg.norm(q[1:]) < 1e-9:
                    if q[0] < -1e-8:
                        ok = False
                        break
                else:
                    sub = clip(sub, -q[1:], q[0])
                if len(sub) < 3:
                    ok = False
                    break
            if not ok or area(sub) < 1e-12:
                continue
            L = np.zeros((m, 3))
            L[list(ss)] = L0
            V = np.linalg.lstsq(F.T, -(H @ W + G + p["A"].T @ L), rcond=1e-10)[0]
            if abs(H @ W + G + p["A"].T @ L + F.T @ V).max() > 1e-8:
                continue
            out.append((sub, L, V))
    return out


def enumerate_regions(p):
    HH = [s["H"] for s in p["stages"]]
    GG = [np.column_stack([s["g0"], s["g1"], np.zeros(6)]) for s in p["stages"]]
    BB = p["priority_designs"]
    cells = []
    for W, poly, slack in lex_candidates(p, HH, GG):
        F = p["E"]
        states = [(poly, [], [])]
        for j, (H, G) in enumerate(zip(HH, GG)):
            duals = dual_regions(p, W, poly, slack, H, G, F)
            states2 = []
            for ss, ls, es in states:
                for ds, L, V in duals:
                    shape = Polygon(ss).intersection(Polygon(ds))
                    if shape.geom_type == "Polygon" and shape.area > 1e-12:
                        states2.append(
                            (
                                np.array(shape.exterior.coords[:-1]),
                                ls + [L.tolist()],
                                es + [V.tolist()],
                            )
                        )
            states = states2
            if not states:
                break
            if j < 2:
                F = np.vstack([F, BB[j]])
        for v, duals, e in states:
            cells.append(
                dict(
                    vertices=v.tolist(),
                    weights=W.tolist(),
                    multipliers=duals,
                    equality_multiplier=e,
                )
            )
    covered = Polygon()
    keep = []
    for cell in sorted(cells, key=lambda c: -Polygon(c["vertices"]).area):
        shape = Polygon(cell["vertices"])
        if shape.difference(covered).area > 1e-14:
            keep.append(cell)
            covered = covered.union(shape)
    print("certified hierarchy regions", len(keep), flush=True)
    return keep
