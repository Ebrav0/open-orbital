# AGENT MAP: model revision 6 runtime ("Real World Physics"). worker.py calls Engine for runs with meta.realistic.
# Gravity stays REBOUND's leapfrog tree. This module adds, per step: an accuracy-limited global timestep, isothermal SPH
# gas forces (kick-drift-kick around the gravity step), a local star-formation law, and stellar-population mass return
# and supernova momentum feedback. Every transfer conserves momentum exactly. Revision <= 5 runs never import it.
"""Hydrodynamics, star formation and feedback for model revision 6. CPU only, numpy + scipy."""
import ctypes,math
import numpy as np
from scipy.spatial import cKDTree
import rebound
import stellar
from stellar import MYR_PER_TIME,V_KMS,GAS,PROTO,MS

C_S=10./V_KMS                 # isothermal sound speed, 10 km/s (10^4 K ionized ISM)
N_NGB=32                      # SPH neighbours inside the 2h kernel support
H_MIN_EPS=.25                 # smoothing length floor, in units of the gravitational softening
COURANT=.3;ALPHA=1.           # Courant factor; Monaghan (1997) signal-velocity viscosity with a Balsara switch
ETA=.025                      # dt <= sqrt(2 eta eps / |a|)  (GADGET-2)
# Code density (1e10 Msun / (3 kpc)^3) -> hydrogen number density per cm^3, hydrogen mass fraction 0.76.
NH_PER_CODE=1e10/3000.**3*1.98847e33/3.0857e18**3*.76/1.6726e-24
N_TH=.1                       # star-formation threshold, H/cm^3 (Schaye & Dalla Vecchia 2008)
EPS_FF=.01                    # stars formed per free-fall time (Krumholz, Dekel & McKee 2012)
P_SN=2.8e5/1e10/V_KMS         # terminal momentum per supernova, 2.8e5 Msun km/s (Kim & Ostriker 2015), code units
YOUNG_MYR=10.                 # populations younger than this are drawn as 'young stars'
FB_NGB=32;FB_RMAX=1./3        # feedback and mass return go to the 32 nearest gas particles within 1 kpc
RELEASE=1e-3                  # an old population releases its returned mass once it exceeds this fraction of its mass

def _w(q):return np.where(q<1,1-1.5*q*q+.75*q**3,np.where(q<2,.25*(2-q)**3,0.))
def _dw(q):return np.where(q<1,-3*q+2.25*q*q,np.where(q<2,-.75*(2-q)**2,0.))

def particle_view(s):
    """Writable (N, 14) float64 view of REBOUND's particle array: x y z vx vy vz ax ay az m r, then pointers."""
    P=rebound.Particle
    if ctypes.sizeof(P)!=112 or [f[0] for f in P._fields_][:11]!=['x','y','z','vx','vy','vz','ax','ay','az','m','r']:
        raise RuntimeError('Unexpected REBOUND particle layout; Real World Physics needs REBOUND 5.1 on a 64-bit build.')
    raw=(ctypes.c_double*(s.N*14)).from_address(ctypes.addressof(s._particles.contents))
    return np.frombuffer(raw,dtype=np.float64).reshape(s.N,14)

def sph(x,v,m,h_min,cs=C_S,alpha=ALPHA):
    """Isothermal SPH (cubic spline, support 2h, 32 neighbours). Returns accelerations, density, smoothing length,
    velocity divergence and the Courant step. Pair forces are antisymmetric, so total momentum is conserved exactly."""
    n=len(m);k=min(2*N_NGB,n);kn=min(N_NGB,k-1)
    d,j=cKDTree(x).query(x,k,workers=-1)
    h=np.maximum(.5*d[:,kn],h_min)
    inside=d<2*h[:,None]
    rho=np.sum(np.where(inside,m[j]*_w(d/h[:,None]),0.),axis=1)/(np.pi*h**3)
    own=np.arange(n)[:,None];mask=inside&(j!=own)
    I=np.broadcast_to(own,j.shape)[mask];J=j[mask]
    # velocity divergence and curl for the Balsara switch (gather, own h)
    dx=x[I]-x[J];r=np.maximum(np.linalg.norm(dx,axis=1),1e-12);gi=_dw(r/h[I])/(np.pi*h[I]**4)/r
    dv=v[I]-v[J];grad=gi[:,None]*dx
    divv=-np.bincount(I,m[J]*np.sum(dv*grad,axis=1),n)/rho
    cr=np.cross(dv,grad)*m[J][:,None];curl=np.sqrt(sum(np.bincount(I,cr[:,c],n)**2 for c in range(3)))/rho
    fB=np.abs(divv)/(np.abs(divv)+curl+1e-4*cs/h)
    # unique unordered pairs from the union of both neighbour lists
    key=np.unique(np.minimum(I,J).astype(np.int64)*n+np.maximum(I,J));A=key//n;B=key%n
    dx=x[A]-x[B];r=np.maximum(np.linalg.norm(dx,axis=1),1e-12)
    g=.5*(_dw(r/h[A])/(np.pi*h[A]**4)+_dw(r/h[B])/(np.pi*h[B]**4))/r      # grad_A W = g * dx  (g <= 0)
    w=np.sum((v[A]-v[B])*dx,axis=1)/r
    vsig=2*cs-3*np.minimum(w,0.)
    visc=np.where(w<0,-alpha*.5*vsig*w/(.5*(rho[A]+rho[B])),0.)*.5*(fB[A]+fB[B])
    f=((cs*cs/rho[A]+cs*cs/rho[B]+visc)*g)[:,None]*dx
    acc=np.zeros((n,3))
    for c in range(3):acc[:,c]=np.bincount(B,m[A]*f[:,c],n)-np.bincount(A,m[B]*f[:,c],n)
    dt=COURANT*min(float(np.min(h))/(2*cs),float(np.min(np.minimum(h[A],h[B])/vsig)) if len(A) else math.inf)
    return acc,rho,h,divv,dt

class Engine:
    """Per-step physics of a revision-6 run. Holds no state that is not rebuilt from the simulation and baryons,
    so a resumed checkpoint continues identically."""
    def __init__(self,s,meta,baryons,params):
        self.s=s;self.b=baryons;self.eps=float(s.softening);self.h_min=H_MIN_EPS*self.eps
        ph=meta.get('physics') or {}
        self.dt_init=float(ph.get('dt_initial',s.dt));self.dt_max=float(ph.get('dt_max',.02))
        self.ret,self.nsn=stellar.ssp_tables(params['imf_mmin'],params['imf_mmax'])
        self.seed=int(meta.get('seed',0));self.P=particle_view(s)
        self.gas=None;self.acc=None;self.rho=None;self.courant=math.inf
        self.stats=dict(dt=float(s.dt),dt_min=math.inf,limiter='',steps=0,gas=0,sf_particles=0)

    def _sph(self):
        P=self.P;gi=np.flatnonzero(self.b['type']==GAS);self.gas=gi
        if len(gi)<N_NGB+1:self.acc=None;self.rho=None;self.courant=math.inf;return
        self.acc,self.rho,self.h,self.divv,self.courant=sph(P[gi,0:3].copy(),P[gi,3:6].copy(),P[gi,9].copy(),self.h_min)

    def hydro_kick(self,dt):
        self._sph()
        if self.acc is not None:self.P[self.gas,3:6]+=self.acc*dt

    def choose_dt(self,remaining):
        """Largest global step with dt <= sqrt(2 eta eps/|a|) for every particle and the gas Courant step, shortened
        so an integer number of steps lands exactly on the next saved frame."""
        a=self.P[:,6:9].copy()
        if self.acc is not None:a[self.gas]+=self.acc
        amax=float(np.sqrt(np.max(np.einsum('ij,ij->i',a,a))))
        if amax>0:dt_g=math.sqrt(2*ETA*self.eps/amax)
        else:dt_g=min(self.dt_init,float(self.s.dt) or self.dt_init)    # no forces computed yet (fresh start or resume)
        dt=min(dt_g,self.courant,self.dt_max)
        lim='gravity' if dt==dt_g else 'gas Courant' if dt==self.courant else 'maximum step'
        k=max(1,math.ceil(remaining/dt-1e-9))
        if k==1 and remaining<dt*(1-1e-9):lim='next saved frame'
        dt=remaining/k
        st=self.stats;st.update(dt=dt,limiter=lim);st['dt_min']=min(st['dt_min'],dt);st['steps']+=1
        return dt

    def lifecycle(self,dt):
        """Ageing, stellar-population mass return and supernova momentum, then star formation. Mutates masses and
        velocities in place through the particle view."""
        b=self.b;P=self.P;types=b['type'];age=b['age'];m0=b['m_star'];dt_myr=dt*MYR_PER_TIME
        rng=np.random.default_rng([self.seed&0xffffffff,int(self.s.steps_done)&0xffffffff,6])
        st=np.flatnonzero((types==PROTO)|(types==MS))
        if len(st):
            a0=age[st];a1=a0+dt_myr;age[st]=a1
            types[st[a1>=YOUNG_MYR]]=MS
            dret=m0[st]*(np.interp(a1,stellar.SSP_AGES,self.ret)-np.interp(a0,stellar.SSP_AGES,self.ret))
            nsn=m0[st]*1e10*(np.interp(a1,stellar.SSP_AGES,self.nsn)-np.interp(a0,stellar.SSP_AGES,self.nsn))
            b['pending'][st]+=dret;b['sn_total']+=float(nsn.sum());b['supernovae']=int(round(b['sn_total']))
            go=(nsn>0)|(b['pending'][st]>RELEASE*P[st,9])
            self._feedback(st[go],nsn[go])
        self._form_stars(dt,rng)
        b['born_window_myr']+=dt_myr;self.stats['gas']=int(np.sum(types==GAS))

    def _feedback(self,don,nsn):
        b=self.b;P=self.P;gi=self.gas if self.gas is not None else np.flatnonzero(b['type']==GAS)
        if not len(don):return
        if len(gi)==0:b['p_unused']+=float(np.sum(nsn))*P_SN;return
        k=min(FB_NGB,len(gi));xg=P[gi,0:3]
        d,jj=cKDTree(xg).query(P[don,0:3],k,workers=-1)
        if k==1:d=d[:,None];jj=jj[:,None]
        ok=d<FB_RMAX;cnt=ok.sum(1);has=cnt>0
        b['p_unused']+=float(np.sum(nsn[~has]))*P_SN
        don,nsn,d,jj,ok,cnt=don[has],nsn[has],d[has],jj[has],ok[has],cnt[has]
        if not len(don):return
        wt=ok/cnt[:,None]                                   # equal shares among valid neighbours
        pend=b['pending'][don].copy();b['pending'][don]=0.;b['returned']+=float(pend.sum())
        vs=P[don,3:6].copy();mg=P[gi,9].copy()
        dm=np.bincount(jj.ravel(),(wt*pend[:,None]).ravel(),len(gi))
        dp=np.zeros((len(gi),3))
        for c in range(3):dp[:,c]=np.bincount(jj.ravel(),(wt*pend[:,None]*vs[:,c][:,None]).ravel(),len(gi))
        # Supernova momentum, radial from the population, with the net vector removed so total momentum is unchanged.
        rho=np.sum(np.where(ok,mg[jj],0.),axis=1)/(4/3*np.pi*np.maximum(np.max(np.where(ok,d,0.),axis=1),1e-3)**3)
        p=nsn*P_SN*np.clip(rho*NH_PER_CODE,1e-3,1e4)**-.17
        u=(xg[jj]-P[don,0:3][:,None,:])/np.maximum(d,1e-9)[:,:,None]
        kick=(p[:,None]*wt)[:,:,None]*u
        kick-=wt[:,:,None]*kick.sum(1,keepdims=True)
        for c in range(3):dp[:,c]+=np.bincount(jj.ravel(),kick[:,:,c].ravel(),len(gi))
        b['p_delivered']+=float(np.sum(np.linalg.norm(kick,axis=2)))
        P[don,9]-=pend
        new=mg+dm;P[gi,3:6]=(mg[:,None]*P[gi,3:6]+dp)/new[:,None];P[gi,9]=new

    def _form_stars(self,dt,rng):
        """Gas above N_TH turns into a stellar population with probability 1 - exp(-eps_ff dt / t_ff)."""
        if self.rho is None or self.gas is None or not len(self.gas):return
        gi=self.gas;b=self.b;types=b['type']
        live=types[gi]==GAS
        rho=self.rho;tff=np.sqrt(3*np.pi/(32*np.maximum(rho,1e-30)))
        p=np.where(live&(rho*NH_PER_CODE>=N_TH),1-np.exp(-EPS_FF*dt/tff),0.)
        pick=gi[rng.random(len(gi))<p]
        if not len(pick):return
        mass=self.P[pick,9].copy()
        types[pick]=PROTO;b['age'][pick]=0.;b['m_star'][pick]=mass;b['birth_time'][pick]=self.s.t
        b['births']+=len(pick);b['born_mass']+=float(mass.sum());self.stats['sf_particles']+=len(pick)

    def step(self,remaining,before_gravity=None):
        """One revision-6 step: SPH at the current state, choose dt from it and the stored gravity, half SPH kick,
        REBOUND leapfrog step, half SPH kick at the new state, lifecycle. Everything the step depends on is in the
        checkpoint (positions, velocities, masses, last gravity accelerations, baryons), so a resume is exact."""
        s=self.s;self._sph();dt=self.choose_dt(remaining);s.dt=dt
        if before_gravity:before_gravity(s)
        if self.acc is not None:self.P[self.gas,3:6]+=self.acc*(.5*dt)
        s.steps(1);self.hydro_kick(.5*dt);self.lifecycle(dt)
        return dt

    def take_stats(self):
        """Stats since the previous saved frame (dt_min, steps), then reset those counters."""
        out=dict(self.stats);out['dt_myr']=out['dt']*MYR_PER_TIME;out['dt_min_myr']=out['dt_min']*MYR_PER_TIME if math.isfinite(out['dt_min']) else None
        out.pop('dt_min');self.stats.update(dt_min=math.inf,steps=0,sf_particles=0)
        return out
