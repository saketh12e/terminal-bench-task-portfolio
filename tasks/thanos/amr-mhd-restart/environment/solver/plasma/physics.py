"""Conservative 2D ideal MHD, staggered CT and SSPRK2 (float64, mu0=1).

U[..., :] = rho, mx, my, mz, total energy, Bz.  Bx/By are face
averages.  The returned fluxes/EMFs are *time* integrals, without face
length factors.  No pressure, density, or total-energy floors are used.
"""

from __future__ import annotations

import numpy as np

GAMMA = 5.0 / 3.0
FIELDS = ("rho", "mx", "my", "mz", "E", "Bz")


def _metric(dx, dy):
    if not np.isfinite(dx) or not np.isfinite(dy) or dx <= 0 or dy <= 0:
        raise ValueError("dx and dy must be finite and positive")


def _arrays(u, bx, by):
    u, bx, by = (np.asarray(a, dtype=np.float64) for a in (u, bx, by))
    if u.ndim != 3 or u.shape[-1] != 6 or min(u.shape[:2]) < 1:
        raise ValueError("u must have shape (ny,nx,6), with nonempty cells")
    ny, nx = u.shape[:2]
    if bx.shape != (ny, nx + 1) or by.shape != (ny + 1, nx):
        raise ValueError("bx/by must have shapes (ny,nx+1)/(ny+1,nx)")
    if not all(np.all(np.isfinite(a)) for a in (u, bx, by)):
        raise ValueError("nonfinite MHD state")
    if np.any(u[..., 0] <= 0):
        raise ValueError("nonpositive density")
    return u, bx, by


def _cell_b(bx, by):
    return 0.5 * (bx[:, :-1] + bx[:, 1:]), 0.5 * (by[:-1] + by[1:])


def pressure(u, bx, by):
    """EOS pressure from total E and arithmetic cell-centered face B."""
    u, bx, by = _arrays(u, bx, by)
    bxc, byc = _cell_b(bx, by)
    kinetic = np.sum(u[..., 1:4] ** 2, axis=-1) / (2 * u[..., 0])
    magnetic = 0.5 * (bxc**2 + byc**2 + u[..., 5] ** 2)
    p = (GAMMA - 1) * (u[..., 4] - kinetic - magnetic)
    if not np.all(np.isfinite(p)) or np.any(p <= 0):
        raise ValueError("nonpositive or nonfinite gas pressure")
    return p


def divergence(bx, by, dx, dy):
    """The staggered finite-volume divergence; no centered surrogate."""
    _metric(dx, dy)
    bx, by = (np.asarray(a, dtype=np.float64) for a in (bx, by))
    if bx.ndim != 2 or by.shape != (bx.shape[0] + 1, bx.shape[1] - 1):
        raise ValueError("inconsistent face array shapes")
    if not np.all(np.isfinite(bx)) or not np.all(np.isfinite(by)):
        raise ValueError("nonfinite magnetic field")
    return (bx[:, 1:] - bx[:, :-1]) / dx + (by[1:] - by[:-1]) / dy


def totals(u, dx, dy):
    """Six cell-area integrals, in FIELDS order (no covered-cell mask)."""
    _metric(dx, dy)
    u = np.asarray(u, dtype=np.float64)
    if u.ndim != 3 or u.shape[-1] != 6 or not np.all(np.isfinite(u)):
        raise ValueError("invalid conserved array")
    return np.sum(u, axis=(0, 1)) * dx * dy


def _primitives(u, bx, by):
    p = pressure(u, bx, by)
    bxc, byc = _cell_b(bx, by)
    w = np.empty(u.shape[:-1] + (8,), dtype=np.float64)
    w[..., 0] = u[..., 0]
    w[..., 1:4] = u[..., 1:4] / u[..., :1]
    w[..., 4] = p
    w[..., 5], w[..., 6], w[..., 7] = bxc, byc, u[..., 5]
    return w


def _check_primitives(w):
    if not np.all(np.isfinite(w)) or np.any(w[..., 0] <= 0) or np.any(w[..., 4] <= 0):
        raise ValueError("inadmissible reconstructed MHD state")


def _conserved(w):
    _check_primitives(w)
    q = np.empty(w.shape[:-1] + (6,), dtype=np.float64)
    rho, v, b = w[..., 0], w[..., 1:4], w[..., 5:8]
    q[..., 0] = rho
    q[..., 1:4] = rho[..., None] * v
    q[..., 4] = w[..., 4] / (GAMMA - 1) + 0.5 * rho * np.sum(v**2, axis=-1)
    q[..., 4] += 0.5 * np.sum(b**2, axis=-1)
    q[..., 5] = w[..., 7]
    return q


def _fast_speed(w, axis):
    _check_primitives(w)
    a2 = GAMMA * w[..., 4] / w[..., 0]
    b2 = np.sum(w[..., 5:8] ** 2, axis=-1) / w[..., 0]
    bn2 = w[..., 5 + axis] ** 2 / w[..., 0]
    # Equivalent to (a2+b2)^2-4*a2*bn2, but manifestly nonnegative.
    transverse2 = np.sum(np.delete(w[..., 5:8], axis, axis=-1) ** 2, axis=-1) / w[..., 0]
    discriminant = (a2 - b2) ** 2 + 4 * a2 * transverse2
    cf = np.sqrt(0.5 * (a2 + b2 + np.sqrt(discriminant)))
    if not np.all(np.isfinite(cf)):
        raise ValueError("nonfinite MHD characteristic speed")
    return cf


def cfl_dt(u, bx, by, dx, dy, cfl=0.35):
    """Conservative unsplit timestep estimate from cell MHD fast speeds."""
    _metric(dx, dy)
    if not np.isfinite(cfl) or not 0 < cfl <= 0.5:
        raise ValueError("cfl must lie in (0,0.5]")
    w = _primitives(*_arrays(u, bx, by))
    ax = np.max(np.abs(w[..., 1]) + _fast_speed(w, 0))
    ay = np.max(np.abs(w[..., 2]) + _fast_speed(w, 1))
    return float(cfl / (ax / dx + ay / dy))


def _physical_flux(w, axis):
    q = _conserved(w)
    vn, bn = w[..., 1 + axis], w[..., 5 + axis]
    b, v = w[..., 5:8], w[..., 1:4]
    pt = w[..., 4] + 0.5 * np.sum(b**2, axis=-1)
    f = q * vn[..., None]
    f[..., 1:4] -= bn[..., None] * b
    f[..., 1 + axis] += pt
    f[..., 4] = (q[..., 4] + pt) * vn - bn * np.sum(v * b, axis=-1)
    f[..., 5] = vn * b[..., 2] - v[..., 2] * bn
    return f, q


def _rusanov(left, right, normal_b, axis):
    left, right = left.copy(), right.copy()
    # A face has one normal B; never a jump in that Riemann component.
    left[..., 5 + axis] = right[..., 5 + axis] = normal_b
    fl, ql = _physical_flux(left, axis)
    fr, qr = _physical_flux(right, axis)
    alpha = np.maximum(
        np.abs(left[..., 1 + axis]) + _fast_speed(left, axis),
        np.abs(right[..., 1 + axis]) + _fast_speed(right, axis),
    )
    return 0.5 * (fl + fr) - 0.5 * alpha[..., None] * (qr - ql)


def _slope(a, axis):
    """Undivided monotonized-central slope; outer padded edge is unused."""
    s = np.zeros_like(a)
    mid = [slice(None)] * a.ndim
    lo, hi = mid.copy(), mid.copy()
    mid[axis], lo[axis], hi[axis] = slice(1, -1), slice(None, -2), slice(2, None)
    dl = a[tuple(mid)] - a[tuple(lo)]
    dr = a[tuple(hi)] - a[tuple(mid)]
    limited = np.minimum(np.minimum(2 * np.abs(dl), 2 * np.abs(dr)), 0.5 * np.abs(dl + dr))
    s[tuple(mid)] = np.where(dl * dr > 0, np.sign(dl) * limited, 0.0)
    return s


def _primitive_slopes(w):
    sx, sy = _slope(w, 1), _slope(w, 0)
    # Reduce reconstruction slopes, not evolved fields, to keep every
    # face/quadrant rho and p positive even in an unsplit 2D reconstruction.
    theta = np.ones(w.shape[:2])
    for k in (0, 4):
        excursion = 0.5 * (np.abs(sx[..., k]) + np.abs(sy[..., k]))
        ratio = np.ones_like(theta)
        np.divide(0.95 * w[..., k], excursion, out=ratio, where=excursion > 0)
        theta = np.minimum(theta, ratio)
    return sx * theta[..., None], sy * theta[..., None]


def _periodic_pad(u, bx, by):
    ny, nx = u.shape[:2]
    for first, last in ((bx[:, 0], bx[:, -1]), (by[0], by[-1])):
        scale = max(1.0, float(np.max(np.abs(first))), float(np.max(np.abs(last))))
        if np.max(np.abs(first - last)) > 64 * np.finfo(np.float64).eps * scale:
            raise ValueError("periodic endpoint faces disagree")
    ci, cj = np.arange(-2, nx + 2) % nx, np.arange(-2, ny + 2) % ny
    fi, fj = np.arange(-2, nx + 3) % nx, np.arange(-2, ny + 3) % ny
    return u[cj[:, None], ci], bx[cj[:, None], fi], by[fj[:, None], ci]


def _pad(u, bx, by, fraction, ghost):
    ny, nx = u.shape[:2]
    if ghost is None:
        return _periodic_pad(u, bx, by)
    # External callbacks cannot accidentally mutate the valid RK state.
    padded = ghost(float(fraction), u.copy(), bx.copy(), by.copy())
    if not isinstance(padded, (tuple, list)) or len(padded) != 3:
        raise ValueError("ghost must return padded (u,bx,by)")
    pu, pbx, pby = _arrays(*padded)
    if pu.shape != (ny + 4, nx + 4, 6):
        raise ValueError("ghost callback must provide exactly two ghost cells")
    for valid, interior in (
        (u, pu[2:-2, 2:-2]),
        (bx, pbx[2:-2, 2:-2]),
        (by, pby[2:-2, 2:-2]),
    ):
        if not np.array_equal(valid, interior):
            raise ValueError("ghost callback changed valid cells or boundary-normal faces")
    return pu, pbx, pby


def _stage_fluxes(u, bx, by, fraction, ghost):
    ny, nx = u.shape[:2]
    pu, pbx, pby = _pad(u, bx, by, fraction, ghost)
    w = _primitives(pu, pbx, pby)
    sx, sy = _primitive_slopes(w)
    rows, cols = slice(2, ny + 2), slice(2, nx + 2)
    left, right = slice(1, nx + 2), slice(2, nx + 3)
    bottom, top = slice(1, ny + 2), slice(2, ny + 3)
    fx = _rusanov(w[rows, left] + 0.5 * sx[rows, left],
                  w[rows, right] - 0.5 * sx[rows, right], pbx[rows, right], 0)
    fy = _rusanov(w[bottom, cols] + 0.5 * sy[bottom, cols],
                  w[top, cols] - 0.5 * sy[top, cols], pby[top, cols], 1)

    # Normal-face B is reconstructed only in its tangential direction.
    sbx_y, sby_x = _slope(pbx, 0), _slope(pby, 1)
    bx_b = pbx[bottom, right] + 0.5 * sbx_y[bottom, right]
    bx_t = pbx[top, right] - 0.5 * sbx_y[top, right]
    by_l = pby[top, left] + 0.5 * sby_x[top, left]
    by_r = pby[top, right] - 0.5 * sby_x[top, right]
    quadrants = (
        w[bottom, left] + 0.5 * (sx[bottom, left] + sy[bottom, left]),
        w[bottom, right] + 0.5 * (-sx[bottom, right] + sy[bottom, right]),
        w[top, left] + 0.5 * (sx[top, left] - sy[top, left]),
        w[top, right] - 0.5 * (sx[top, right] + sy[top, right]),
    )
    electric = np.zeros((ny + 1, nx + 1), dtype=np.float64)
    alpha_x, alpha_y = np.zeros_like(electric), np.zeros_like(electric)
    for q, bxn, byn in zip(quadrants, (bx_b, bx_b, bx_t, bx_t), (by_l, by_r, by_l, by_r)):
        q[..., 5], q[..., 6] = bxn, byn
        electric += 0.25 * (q[..., 2] * bxn - q[..., 1] * byn)
        alpha_x = np.maximum(alpha_x, np.abs(q[..., 1]) + _fast_speed(q, 0))
        alpha_y = np.maximum(alpha_y, np.abs(q[..., 2]) + _fast_speed(q, 1))
    electric += 0.5 * alpha_x * (by_r - by_l) - 0.5 * alpha_y * (bx_t - bx_b)
    return fx, fy, electric


def _apply_integrals(u, bx, by, fx, fy, ez, dx, dy):
    un = u - (fx[:, 1:] - fx[:, :-1]) / dx - (fy[1:] - fy[:-1]) / dy
    bxn = bx - (ez[1:] - ez[:-1]) / dy
    byn = by + (ez[:, 1:] - ez[:, :-1]) / dx
    return un, bxn, byn


def advance(u, bx, by, dt, dx, dy, ghost=None):
    """One SSPRK2 step; return new U/Bx/By and integrated Fx/Fy/Ez.

    ghost(fraction,U,Bx,By) is called at fractions 0 and 1 of THIS dt.
    It returns shapes (ny+4,nx+4,6), (ny+4,nx+5), (ny+5,nx+4).
    Valid cells and all valid normal faces must be retained verbatim.
    The parent maps fractions onto its coarse old/predictor time bracket.
    dt selection belongs to the caller; cfl_dt provides a recommendation.
    Invalid input, predictor, ghost or final states raise ValueError.
    """
    _metric(dx, dy)
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError("dt must be finite and positive")
    u, bx, by = _arrays(u, bx, by)
    pressure(u, bx, by)
    f0, g0, e0 = _stage_fluxes(u, bx, by, 0.0, ghost)
    u1, bx1, by1 = _apply_integrals(u, bx, by, dt * f0, dt * g0, dt * e0, dx, dy)
    pressure(u1, bx1, by1)
    f1, g1, e1 = _stage_fluxes(u1, bx1, by1, 1.0, ghost)
    fx, fy, ez = (0.5 * dt * (a + b) for a, b in ((f0, f1), (g0, g1), (e0, e1)))
    un, bxn, byn = _apply_integrals(u, bx, by, fx, fy, ez, dx, dy)
    pressure(un, bxn, byn)
    return un, bxn, byn, fx, fy, ez


def smooth_wave(nx, ny, case=None):
    """Exact averaged circular Alfvén wave on a periodic rectangle.

    Returns (U,Bx,By). case keys: rho=1, p=1, b0=1, amplitude=.1,
    velocity=.15 (bulk speed along k), kx=1, ky=1 (integer wave counts),
    time=0, lx=1, ly=1. gamma is fixed. The branch propagates at
    velocity+b0/sqrt(rho) along k. All returned values are cell/face
    averages, not point samples. Total E is the continuum cell average;
    diagnostic pressure therefore has an O(h^2) averaging discrepancy.
    """
    case = {} if case is None else dict(case)
    allowed = {"rho", "p", "b0", "amplitude", "velocity", "kx", "ky", "time", "lx", "ly"}
    if set(case) - allowed:
        raise ValueError("unknown smooth_wave case keys: " + str(sorted(set(case) - allowed)))
    if int(nx) != nx or int(ny) != ny or min(nx, ny) < 1:
        raise ValueError("nx and ny must be positive integers")
    nx, ny = int(nx), int(ny)
    rho, p = float(case.get("rho", 1.0)), float(case.get("p", 1.0))
    b0, amp = float(case.get("b0", 1.0)), float(case.get("amplitude", 0.1))
    velocity, time = float(case.get("velocity", 0.15)), float(case.get("time", 0.0))
    lx, ly = float(case.get("lx", 1.0)), float(case.get("ly", 1.0))
    kx, ky = case.get("kx", 1), case.get("ky", 1)
    if not np.all(np.isfinite([rho, p, b0, amp, velocity, time, lx, ly, kx, ky])):
        raise ValueError("nonfinite wave parameters")
    if rho <= 0 or p <= 0 or lx <= 0 or ly <= 0:
        raise ValueError("wave density, pressure and lengths must be positive")
    if int(kx) != kx or int(ky) != ky or (kx == 0 and ky == 0):
        raise ValueError("periodic wave counts must be integers, not both zero")
    dx, dy = lx / nx, ly / ny
    wavevector = 2 * np.pi * np.array([kx / lx, ky / ly], dtype=np.float64)
    knorm = float(np.linalg.norm(wavevector))
    n = wavevector / knorm
    transverse = np.array([-n[1], n[0], 0.0])
    omega = knorm * (velocity + b0 / np.sqrt(rho))
    x, y = (np.arange(nx) + 0.5) * dx, (np.arange(ny) + 0.5) * dy
    phi = wavevector[0] * x[None, :] + wavevector[1] * y[:, None] - omega * time
    sinc_x, sinc_y = np.sinc(wavevector[0] * dx / (2 * np.pi)), np.sinc(wavevector[1] * dy / (2 * np.pi))
    c, s = np.cos(phi) * sinc_x * sinc_y, np.sin(phi) * sinc_x * sinc_y
    u = np.zeros((ny, nx, 6), dtype=np.float64)
    u[..., 0] = rho
    u[..., 1] = rho * velocity * n[0] - np.sqrt(rho) * amp * transverse[0] * c
    u[..., 2] = rho * velocity * n[1] - np.sqrt(rho) * amp * transverse[1] * c
    u[..., 3] = -np.sqrt(rho) * amp * s
    u[..., 4] = p / (GAMMA - 1) + 0.5 * rho * velocity**2 + 0.5 * b0**2 + amp**2
    u[..., 5] = amp * s
    phi_x = wavevector[0] * np.arange(nx + 1)[None, :] * dx + wavevector[1] * y[:, None] - omega * time
    phi_y = wavevector[0] * x[None, :] + wavevector[1] * np.arange(ny + 1)[:, None] * dy - omega * time
    bx = b0 * n[0] + amp * transverse[0] * np.cos(phi_x) * sinc_y
    by = b0 * n[1] + amp * transverse[1] * np.cos(phi_y) * sinc_x
    # Enforce identity of the two representations of each periodic face.
    bx[:, -1], by[-1] = bx[:, 0], by[0]
    pressure(u, bx, by)
    return u, bx, by
