"""Space-time interface integrals and conservative coarse/fine synchronization."""
import numpy as np
from .transfer import restrict


def synchronize(u,bx,by,fu,fbx,fby,bounds,coarse_flux,fine_flux,dx,dy):
    x0,x1,y0,y1=bounds
    cx,cy,ce=coarse_flux; fx,fy,fe=fine_flux
    left=(fx[::2,0]+fx[1::2,0])/2-cx[y0:y1,x0]
    right=(fx[::2,-1]+fx[1::2,-1])/2-cx[y0:y1,x1]
    bottom=(fy[0,::2]+fy[0,1::2])/2-cy[y0,x0:x1]
    top=(fy[-1,::2]+fy[-1,1::2])/2-cy[y1,x0:x1]
    left[:,4]=0;right[:,4]=0;bottom[:,4]=0;top[:,4]=0
    u[y0:y1,x0-1]-=left/dx
    u[y0:y1,x1]+=right/dx
    u[y0-1,x0:x1]-=bottom/dy
    u[y1,x0:x1]+=top/dy
    delta=np.zeros_like(ce)
    delta[y0:y1+1,x0]=fe[::2,0]-ce[y0:y1+1,x0]
    delta[y0:y1+1,x1]=fe[::2,-1]-ce[y0:y1+1,x1]
    delta[y0,x0:x1+1]=fe[0,::2]-ce[y0,x0:x1+1]
    delta[y1,x0:x1+1]=fe[-1,::2]-ce[y1,x0:x1+1]
    bx-=np.diff(delta,axis=0)/(2*dy)
    by+=np.diff(delta,axis=1)/(2*dx)
    ru,rx,ry=restrict(fu,fbx,fby)
    u[y0:y1,x0:x1]=ru
    bx[y0:y1,x0:x1+1]=rx
    by[y0:y1+1,x0:x1]=ry
    return {'left':left,'right':right,'bottom':bottom,'top':top,'emf':delta}
