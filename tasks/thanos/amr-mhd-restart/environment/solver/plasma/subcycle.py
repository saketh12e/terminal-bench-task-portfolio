"""Inner refinement integration used by the recovery branch."""
import numpy as np
from .physics import advance
from .transfer import prolong,crop
from .boundary import callback
from .registers import synchronize


class Subcycle:
    def __init__(self,coarse,bounds,h,dt,step=0,owner=1):
        self.coarse=coarse;self.bounds=list(bounds);self.h=h;self.dt=dt
        self.fine=crop(prolong(*coarse,h,h),bounds)
        self.step=step;self.phase='sync';self.owner=owner
        self.old=None;self.coarse_flux=None;self.fine_flux=None;self.last_flux=None

    def clocks(self):
        return self.step*self.dt,self.step*self.dt

    def tick(self,external_ghost):
        # The integration service commits complete local intervals.
        start=tuple(a.copy() for a in self.coarse)
        parent=advance(*start,self.dt,self.h,self.h,ghost=external_ghost)
        self.coarse=parent[:3]
        ny,nx=self.fine[0].shape[:2]
        accum=(np.zeros((ny,nx+1,6)),np.zeros((ny+1,nx,6)),np.zeros((ny+1,nx+1)))
        for half in range(2):
            child=advance(*self.fine,self.dt/2,self.h/2,self.h/2,
                          ghost=callback(start,self.coarse,self.bounds,half,self.h))
            self.fine=child[:3]
            accum=tuple((a+b)/2 for a,b in zip(accum,child[3:]))
        synchronize(*self.coarse,*self.fine,self.bounds,parent[3:],accum,self.h,self.h)
        self.last_flux=tuple(a.copy() for a in parent[3:])
        self.step+=1

    def migrate(self,owner):
        # Logical transport accepts complete state packages in arbitrary order.
        wire={(name,k):a.copy() for name in ('coarse','fine')
              for k,a in enumerate(getattr(self,name))}
        packet={key:wire[key].copy() for key in reversed(list(wire))}
        for name in ('coarse','fine'):
            setattr(self,name,tuple(packet[(name,k)] for k in range(3)))
        self.owner=int(owner)
