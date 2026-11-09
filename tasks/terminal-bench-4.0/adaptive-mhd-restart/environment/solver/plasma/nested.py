"""Recursive coarse/fine recovery with a properly nested third level."""
import numpy as np
from .hierarchy import Hierarchy
from .subcycle import Subcycle
from .boundary import callback
from .initial import pressure,divergence
from .physics import pressure as require_admissible
from .regrid import replace,potential


def global_bounds(outer,inner):
    x0,x1,y0,y1=inner
    return [x0,x1,y0,y1]


def retain(old,old_bounds,new,new_bounds,h):
    """Retain finest overlap using global level-one indices and one gauge."""
    u,bx,by=old;nu,nx,ny=(a.copy() for a in new)
    x0,x1,y0,y1=old_bounds;X0,X1,Y0,Y1=new_bounds
    lx,hx=max(x0,X0),min(x1,X1);ly,hy=max(y0,Y0),min(y1,Y1)
    if lx<hx and ly<hy:
        oj,oi=2*(ly-y0),2*(lx-x0);nj,ni=2*(ly-Y0),2*(lx-X0)
        rows,cols=2*(hy-ly),2*(hx-lx)
        nu[nj:nj+rows,ni:ni+cols]=u[oj:oj+rows,oi:oi+cols]
        oa=potential(bx,by,h);na=potential(nx,ny,h)
        shift=na[nj,ni]-oa[oj,oi]
        na[nj:nj+rows+1,ni:ni+cols+1]=oa[oj:oj+rows+1,oi:oi+cols+1]+shift
        nx=np.diff(na,axis=0)/h;ny=-np.diff(na,axis=1)/h
    require_admissible(nu,nx,ny)
    return nu,nx,ny


class NestedHierarchy(Hierarchy):
    def __init__(self,config):
        self.child=None;self.nested_epoch=0
        super().__init__(config)
        inner=config.get('nested_patch')
        if inner is not None:self.child=Subcycle(self.fine,inner,self.h/2,self.dt/2,owner=config.get('nested_owner',1))
        self.initial_nested=tuple(a.copy() for a in self.child.fine) if self.child else None
        self.initial_nested_bounds=list(inner) if inner is not None else None
        self.initial_total=self.total();self.history=[];self.record()

    def total(self):
        result=super().total()
        child=getattr(self,'child',None)
        if child is not None:
            x0,x1,y0,y1=child.bounds
            result-=self.fine[0][y0:y1,x0:x1].sum(axis=(0,1))*(self.h/2)**2
            result+=child.fine[0].sum(axis=(0,1))*(self.h/4)**2
        return result

    def clocks(self):
        coarse,fine=super().clocks()
        if self.child is not None:fine=self.child.clocks()[0]
        return coarse,fine

    def diagnostics(self):
        if self.child is None:return super().diagnostics()
        cmask=np.ones(self.coarse[0].shape[:2],bool);x0,x1,y0,y1=self.bounds;cmask[y0:y1,x0:x1]=False
        fmask=np.ones(self.fine[0].shape[:2],bool);x0,x1,y0,y1=self.child.bounds;fmask[y0:y1,x0:x1]=False
        leaves=[(self.coarse,cmask,self.h),(self.fine,fmask,self.h/2),
                (self.child.fine,np.ones(self.child.fine[0].shape[:2],bool),self.h/4)]
        return {'total':self.total().tolist(),
                'rho_min':float(min(s[0][...,0][m].min() for s,m,h in leaves)),
                'pressure_min':float(min(pressure(*s)[m].min() for s,m,h in leaves)),
                'divergence_max':float(max(abs(divergence(*s[1:],h,h))[m].max() for s,m,h in leaves))}

    def migrate(self,owner,level=1):
        if level==1:
            super().migrate(owner)
            if self.child is not None:self.child.coarse=self.fine
        elif level==2 and self.child is not None:
            old=self.child.owner;self.child.migrate(owner);self.fine=self.child.coarse
            self.transfers.append({'step':self.step,'phase':self.phase,'child_phase':self.child.phase,
                                   'level':2,'from':old,'to':int(owner)})
        else:raise ValueError('migration refers to absent refinement level')

    def events(self):
        events=self.config.get('events',[])
        while self.event_cursor<len(events):
            event=events[self.event_cursor]
            child_phase=self.child.phase if self.child is not None else 'sync'
            if (event['step'],event['phase'])!=(self.step,self.phase):break
            if event['kind']=='migrate':self.migrate(event['owner'],event.get('level',1))
            elif event['kind'] in ('regrid','regrid_nested'):
                if self.phase!='sync' or child_phase!='sync':raise ValueError('topology change before all levels synchronize')
                old_child=self.child
                old_nested=tuple(a.copy() for a in old_child.fine) if old_child else None
                old_global=global_bounds(self.bounds,old_child.bounds) if old_child else None
                replacement_coarse=tuple(a.copy() for a in self.coarse)
                if event['kind']=='regrid':
                    updated=replace(replacement_coarse,self.fine,self.bounds,event['patch'],self.h)
                    new_outer=list(event['patch'])
                    inner=event.get('nested_patch',old_child.bounds if old_child else None)
                else:
                    updated=tuple(a.copy() for a in self.fine);new_outer=self.bounds.copy();inner=event['patch']
                new_child=Subcycle(updated,inner,self.h/2,self.dt/2,step=2*self.step,
                                   owner=old_child.owner if old_child else self.config.get('nested_owner',1)) if inner is not None else None
                if old_child is not None and new_child is not None:
                    new_child.fine=retain(old_nested,old_global,new_child.fine,global_bounds(new_outer,inner),self.h/4)
                self.coarse=replacement_coarse;self.fine=updated;self.bounds=new_outer;self.child=new_child
                self.epoch+=1;self.nested_epoch+=1;self.record()
            else:raise ValueError('unknown hierarchy event')
            self.event_cursor+=1

    def tick(self):
        if self.child is None or self.phase in ('sync','fine2'):
            super().tick()
            return
        half=0 if self.phase=='predicted' else 1
        self.child.tick(callback(self.old,self.coarse,self.bounds,half,self.h))
        self.fine=self.child.coarse
        if self.child.phase=='sync':
            self.fine_flux=tuple(a.copy() for a in self.child.last_flux)
            self.child.last_flux=None
            self.phase='fine1' if half==0 else 'fine2'

    def run(self,stop=None):
        while True:
            self.events()
            child_phase=self.child.phase if self.child else 'sync'
            if stop and (self.step,self.phase,child_phase)==(stop['step'],stop['phase'],stop.get('child_phase','sync')):break
            if self.step==self.config['steps'] and self.phase=='sync':break
            self.tick()
        return self
