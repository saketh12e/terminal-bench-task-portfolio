"""Smooth MHD initial states with diagnostic-pressure energy convention."""
import numpy as np

GAMMA = 5/3


def state(n, case, time=0.0):
    h=1/n
    y,x=np.meshgrid((np.arange(n)+.5)*h,(np.arange(n)+.5)*h,indexing='ij')
    yx,xx=np.meshgrid((np.arange(n)+.5)*h,np.arange(n+1)*h,indexing='ij')
    yy,xy=np.meshgrid(np.arange(n+1)*h,(np.arange(n)+.5)*h,indexing='ij')
    kind=case.get('kind','alfven')
    kx,ky=case.get('wavevector',[1,0]); norm=np.hypot(kx,ky)
    ex,ey=kx/norm,ky/norm
    amp=case.get('amplitude',.05); phase=case.get('phase',.13)
    rho0=case.get('density',1.); pressure=case.get('pressure',1.)
    field=case.get('field',.7); speed=case.get('velocity',.25)
    def angle(x,y):
        wavespeed=speed+(field/np.sqrt(rho0) if kind=='alfven' else 0.)
        return 2*np.pi*(kx*x+ky*y-norm*wavespeed*time)+phase
    a=angle(x,y)
    sx=np.sinc(kx*h); sy=np.sinc(ky*h)
    vx=np.full_like(x,speed*ex); vy=np.full_like(x,speed*ey); vz=np.zeros_like(x)
    bz=np.zeros_like(x)
    if kind=='alfven':
        bt=amp*np.cos(a)*sx*sy
        bz=amp*np.sin(a)*sx*sy
        vx+=ey*bt/np.sqrt(rho0); vy-=ex*bt/np.sqrt(rho0); vz=-bz/np.sqrt(rho0)
        bx=field*ex-ey*amp*np.cos(angle(xx,yx))*sy
        by=field*ey+ex*amp*np.cos(angle(xy,yy))*sx
        rho=np.full_like(x,rho0)
    elif kind=='entropy':
        rho=rho0*(1+amp*np.sin(a)*sx*sy)
        bx=np.full_like(xx,field*.8); by=np.full_like(xy,field*.6)
    elif kind=='loop':
        # Periodic smooth magnetic loop, generated as a discrete curl.
        xv,yv=np.meshgrid(np.arange(n+1)*h,np.arange(n+1)*h,indexing='xy')
        potential=amp*np.cos(2*np.pi*(xv-speed*ex*time)+phase)*np.cos(2*np.pi*(yv-speed*ey*time)) /(2*np.pi)
        bx=np.diff(potential,axis=0)/h
        by=-np.diff(potential,axis=1)/h
        rho=np.full_like(x,rho0)
    elif kind=='pressure':
        rho=np.full_like(x,rho0)
        pressure=pressure*(1+amp*np.exp(-((x-.5)**2+(y-.5)**2)/.025))
        bx=np.full_like(xx,field*.8); by=np.full_like(xy,field*.6)
    else:
        raise ValueError('unsupported physical case')
    bxc=(bx[:,:-1]+bx[:,1:])/2; byc=(by[:-1]+by[1:])/2
    energy=pressure/(GAMMA-1)+rho*(vx*vx+vy*vy+vz*vz)/2+(bxc*bxc+byc*byc+bz*bz)/2
    return np.stack((rho,rho*vx,rho*vy,rho*vz,energy,bz),axis=-1),bx,by


def pressure(u,bx,by):
    bc2=((bx[:,:-1]+bx[:,1:])/2)**2+((by[:-1]+by[1:])/2)**2+u[...,5]**2
    return (GAMMA-1)*(u[...,4]-(u[...,1:4]**2).sum(axis=-1)/(2*u[...,0])-bc2/2)


def divergence(bx,by,dx,dy):
    return np.diff(bx,axis=1)/dx+np.diff(by,axis=0)/dy
