"""Conservative factor-two transfers on a staggered Cartesian mesh."""
import numpy as np
from .physics import pressure


def limited(a, axis):
    left = a - np.roll(a, 1, axis=axis)
    right = np.roll(a, -1, axis=axis) - a
    return np.where(left * right > 0, np.sign(left) * np.minimum(abs(left), abs(right)), 0.0)


def cells(u):
    sy, sx = limited(u, 0), limited(u, 1)
    out = np.empty((2*u.shape[0], 2*u.shape[1], u.shape[2]))
    for j in range(2):
        for i in range(2):
            out[j::2, i::2] = u + (2*j-1)*sy/4 + (2*i-1)*sx/4
    return out


def faces(bx, by, dx, dy):
    """Split exterior faces conservatively; project four interior faces.

    The tiny Neumann solve imposes each child's parent divergence and
    chooses the minimum correction of bilinear interior-face estimates.
    """
    ny, nx = bx.shape[0], by.shape[1]
    fx = np.empty((2*ny, 2*nx+1))
    fy = np.empty((2*ny+1, 2*nx))
    sx, sy = limited(bx, 0), limited(by, 1)
    fx[0::2, 0::2] = bx-sx/4
    fx[1::2, 0::2] = bx+sx/4
    fy[0::2, 0::2] = by-sy/4
    fy[0::2, 1::2] = by+sy/4
    l0, l1 = fx[0::2, 0:-1:2], fx[1::2, 0:-1:2]
    r0, r1 = fx[0::2, 2::2], fx[1::2, 2::2]
    b0, b1 = fy[0:-1:2, 0::2], fy[0:-1:2, 1::2]
    t0, t1 = fy[2::2, 0::2], fy[2::2, 1::2]
    q = np.stack(((l0+r0)/2, (l1+r1)/2, (b0+t0)/2, (b1+t1)/2), axis=-1)
    hx, hy = dx/2, dy/2
    fx[0::2,1::2], fx[1::2,1::2] = q[...,0], q[...,1]
    fy[1::2,0::2], fy[1::2,1::2] = q[...,2], q[...,3]
    return fx, fy


def prolong(u, bx, by, dx, dy):
    pressure(u,bx,by)
    fx, fy = faces(bx, by, dx, dy)
    coarse_p=pressure(u,bx,by)
    parent=np.repeat(np.repeat(u,2,axis=0),2,axis=1)
    increment=cells(u)-parent
    theta=np.ones(u.shape[:2])
    magnetic=((fx[:,:-1]+fx[:,1:])**2+(fy[:-1]+fy[1:])**2)/8
    for attempt in range(30):
        candidate=parent+increment*np.repeat(np.repeat(theta,2,axis=0),2,axis=1)[...,None]
        rho=candidate[...,0]
        bad=(rho<=0) | ~np.isfinite(candidate).all(axis=-1)
        thermal=candidate[...,4]-np.sum(candidate[...,1:4]**2,axis=-1)/(2*np.maximum(rho,1e-300))-magnetic-candidate[...,5]**2/2
        bad |= thermal<=0
        if not bad.any():
            pressure(candidate,fx,fy)
            pchild=cells(coarse_p[...,None])[...,0]
            candidate[...,4]=pchild/(2/3)+np.sum(candidate[...,1:4]**2,axis=-1)/(2*candidate[...,0])+magnetic+candidate[...,5]**2/2
            return candidate,fx,fy
        parents=bad[::2,::2]|bad[1::2,::2]|bad[::2,1::2]|bad[1::2,1::2]
        theta[parents]*=.5
    raise ValueError('refinement has insufficient conserved energy for admissible child fields')


def restrict(u, bx, by):
    return ((u[::2,::2]+u[1::2,::2]+u[::2,1::2]+u[1::2,1::2])/4,
            (bx[::2,::2]+np.roll(bx,1,axis=0)[::2,::2])/2,
            (by[::2,::2]+np.roll(by,1,axis=1)[::2,::2])/2)


def crop(full, bounds, ghosts=0):
    u,bx,by = full
    x0,x1,y0,y1 = (2*v for v in bounds)
    ny,nx = u.shape[:2]
    ix = np.arange(x0-ghosts,x1+ghosts)%nx
    iy = np.arange(y0-ghosts,y1+ghosts)%ny
    ixf = np.arange(x0-ghosts,x1+ghosts+1)%nx
    iyf = np.arange(y0-ghosts,y1+ghosts+1)%ny
    return u[np.ix_(iy,ix)].copy(), bx[np.ix_(iy,ixf)].copy(), by[np.ix_(iyf,ix)].copy()
