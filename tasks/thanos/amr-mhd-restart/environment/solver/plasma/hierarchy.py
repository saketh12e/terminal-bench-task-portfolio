"""Two-level Berger-Colella subcycling with staggered CT synchronization."""
import copy
import numpy as np
from .initial import state, pressure, divergence
from .physics import advance
from .transfer import prolong,crop,restrict
from .boundary import callback
from .registers import synchronize
from .regrid import replace


PHASES=('sync','predicted','fine1','fine2')


class Hierarchy:
    def __init__(self,config):
        self.config=copy.deepcopy(config)
        self.n=int(config['n']); self.h=1/self.n
        self.dt=float(config['dt']); self.step=0; self.phase='sync'
        self.bounds=list(config['patch']); self.owner=int(config.get('owner',0))
        self.epoch=0; self.event_cursor=0
        self.coarse=state(self.n,config['case'])
        self.fine=crop(prolong(*self.coarse,self.h,self.h),self.bounds)
        self.old=None; self.coarse_flux=None; self.fine_flux=None
        self.history=[]; self.transfers=[]
        self.initial_coarse=tuple(a.copy() for a in self.coarse)
        self.initial_fine=tuple(a.copy() for a in self.fine)
        self.initial_bounds=self.bounds.copy()
        self.initial_total=self.total()
        self.record()

    def total(self):
        x0,x1,y0,y1=self.bounds
        masked=self.coarse[0].copy(); masked[y0:y1,x0:x1]=0
        return masked.sum(axis=(0,1))*self.h**2+self.fine[0].sum(axis=(0,1))*(self.h/2)**2

    def diagnostics(self):
        mask=np.ones((self.n,self.n),bool)
        x0,x1,y0,y1=self.bounds;mask[y0:y1,x0:x1]=False
        p0=pressure(*self.coarse);p1=pressure(*self.fine)
        d0=divergence(*self.coarse[1:],self.h,self.h)
        d1=divergence(*self.fine[1:],self.h/2,self.h/2)
        return {'total':self.total().tolist(),'rho_min':float(min(self.coarse[0][...,0][mask].min(),self.fine[0][...,0].min())),
                'pressure_min':float(min(p0[mask].min(),p1.min())),
                'divergence_max':float(max(abs(d0[mask]).max(),abs(d1).max()))}

    def clocks(self):
        coarse=(self.step+(self.phase!='sync'))*self.dt
        fine=(self.step+{'sync':0,'predicted':0,'fine1':.5,'fine2':1}[self.phase])*self.dt
        return coarse,fine

    def record(self):
        self.history.append({'step':self.step,'phase':self.phase,'bounds':self.bounds.copy(),
                             'owner':self.owner,'epoch':self.epoch,'time':self.clocks()[0],**self.diagnostics()})

    def migrate(self,new_owner):
        # Serialize actual transferable state, then receive it in a different
        # wire order. Stable field identifiers, not position, identify payloads.
        payload={}
        for name in ('coarse','fine','old','coarse_flux','fine_flux'):
            value=getattr(self,name)
            if value is not None:
                for k,a in enumerate(value):payload[(name,k)]=np.array(a,copy=True)
        received={key:payload[key].copy() for key in reversed(list(payload))}
        for name in ('coarse','fine','old','coarse_flux','fine_flux'):
            if getattr(self,name) is not None:
                setattr(self,name,tuple(received[(name,k)] for k in range(3)))
        self.transfers.append({'step':self.step,'phase':self.phase,'from':self.owner,'to':int(new_owner),'arrays':len(received)})
        self.owner=int(new_owner)
        if self.fine_flux is not None:self.fine_flux=tuple(np.zeros_like(a) for a in self.fine_flux)

    def events(self):
        events=self.config.get('events',[])
        while self.event_cursor<len(events):
            e=events[self.event_cursor]
            if (e['step'],e['phase'])!=(self.step,self.phase):break
            if e['kind']=='migrate':self.migrate(e['owner'])
            elif e['kind']=='regrid':
                if self.phase!='sync':raise ValueError('regrid requires synchronization')
                self.fine=replace(self.coarse,self.fine,self.bounds,e['patch'],self.h)
                self.bounds=list(e['patch']);self.epoch+=1
                self.record()
            else:raise ValueError('unknown schedule event')
            self.event_cursor+=1

    def tick(self):
        if self.phase=='sync':
            self.old=tuple(a.copy() for a in self.coarse)
            values=advance(*self.coarse,self.dt,self.h,self.h)
            self.coarse=values[:3];self.coarse_flux=values[3:]
            fu,fx,fy=self.fine
            self.fine_flux=(np.zeros((fu.shape[0],fu.shape[1]+1,6)),
                            np.zeros((fu.shape[0]+1,fu.shape[1],6)),np.zeros((fu.shape[0]+1,fu.shape[1]+1)))
            self.phase='predicted'
        elif self.phase in ('predicted','fine1'):
            half=0 if self.phase=='predicted' else 1
            values=advance(*self.fine,self.dt/2,self.h/2,self.h/2,ghost=callback(self.old,self.coarse,self.bounds,half,self.h))
            self.fine=values[:3]
            self.fine_flux=tuple((a+b)/2 for a,b in zip(self.fine_flux,values[3:]))
            self.phase='fine1' if half==0 else 'fine2'
        else:
            synchronize(*self.coarse,*self.fine,self.bounds,self.coarse_flux,self.fine_flux,self.h,self.h)
            self.old=None;self.coarse_flux=None;self.fine_flux=None
            self.step+=1;self.phase='sync';self.record()

    def run(self,stop=None):
        while True:
            self.events()
            if stop and self.step==stop['step'] and self.phase==stop['phase']:break
            if self.step==self.config['steps'] and self.phase=='sync':break
            self.tick()
        return self
