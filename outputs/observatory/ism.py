# AGENT MAP: laboratory two-phase ISM on the existing O(N) density grid.
# Not SPH, not a Riemann solver, not GADGET. Gas is still superparticles.
# Forces are real (pressure, ram, shock heat) and feed REBOUND velocities.
# Cooling uses a CIE-like Λ(T,Z) with Field-style warm/hot attractors and
# Stinson-like delayed cooling after supernovae. Star formation may only
# consume cold, dense, non-expanding gas. Isolated collisionless ICs are
# unchanged because this module never runs when lifecycle is off.
"""Grid ISM: cooling, pressure, ram drag, blastwave heat."""
import numpy as np

# Must match stellar.py type ids and physics.py unit conventions.
GAS,HOT=0,9
CELL=.15                    # ~450 pc; same grid as stellar.py
MYR_PER_TIME=24.50
V_KMS=119.7
GAMMA=5./3.
Z_SOLAR=.02
T_FLOOR=8e3                 # unresolved cold molecular phase
T_HOT_ON=1.2e5              # type 0 → 9 (ionized / shocked)
T_HOT_OFF=6e4               # type 9 → 0 hysteresis
T_SF=3.5e4                  # SF only below this
T_MAX=3e7
BLAST_DELAY_MYR=15.         # Stinson-like; simulation Myr, not the stellar clock
YIELD_SN=.02                # metal mass / ejecta mass, massive-star death
YIELD_AGB=.002
ALPHA_VISC=.8
# T = T_PER_U * μ * u_code.  V=119.7 km/s, γ=5/3, k/m_H.
T_PER_U=1.1572e6
# n_H (cm^-3) = N_H0 * ρ_code / μ.  1 code density = 1e10 M☉ / (3 kpc)^3.
N_H0=14.98
VOL=CELL**3
AREA=CELL*CELL
# Laboratory UV/turbulent heating floor (erg s^-1 per H). Set so n~1 cm^-3
# gas sits near 10^4 K; not a Haardt–Madau background.
GAMMA_PE=2.0e-22
# du_code/dt_code = n_H Λ /(μ m_H) * t_code / V^2
COOL_PREFAC=3.226e24        # seconds-and-cgs collected; see HANDOFF
M_H=1.6726219e-24
V2=V_KMS*1e5
V2=V2*V2
DT_PHYS=MYR_PER_TIME*3.15576e13

# CIE-like log Λ (erg cm^3 s^-1). Primordial H/He + solar-scaled metals.
# Metal peak near 10^5.4 K is the Field-unstable Fe/CNO branch.
_LOGT=np.array([3.0,3.7,4.0,4.3,4.6,5.0,5.4,5.8,6.2,6.7,7.3,8.0])
_LOGP=np.array([-24.2,-23.3,-22.5,-22.15,-22.45,-22.85,-23.05,-22.95,-22.7,-22.5,-22.5,-22.75])
_LOGZ=np.array([-24.8,-23.6,-22.9,-21.95,-21.55,-21.35,-21.05,-21.55,-22.05,-22.45,-22.85,-23.25])

def cooling_lambda(T,Zs):
    """Λ(T,Z) in erg cm^3 s^-1. Zs is Z/Z☉. Vectorized."""
    logT=np.log10(np.clip(np.asarray(T,dtype=np.float64),1e2,1e9))
    Zs=np.asarray(Zs,dtype=np.float64)
    return 10**np.interp(logT,_LOGT,_LOGP)+np.clip(Zs,0,8)*10**np.interp(logT,_LOGT,_LOGZ)

def mu_of_T(T):
    """Mean weight per particle. Neutral μ=1.4 → ionized μ=0.62 around 1.5e4 K."""
    ratio=np.clip(np.asarray(T,dtype=np.float64),10,1e9)/1.5e4
    x=1./(1.+ratio**-4)
    return 1.4*(1-x)+.62*x

def temperature(u):
    """Return (T[K], μ) from specific internal energy in code units."""
    u=np.maximum(np.asarray(u,dtype=np.float64),1e-18)
    mu=np.full_like(u,.9)
    for _ in range(3):
        T=T_PER_U*mu*u
        mu=mu_of_T(T)
    return T,mu

def u_from_T(T):
    T=np.asarray(T,dtype=np.float64)
    return T/(T_PER_U*mu_of_T(T))

U_MIN=float(u_from_T(T_FLOOR));U_MAX=float(u_from_T(T_MAX))

def is_gas(types):
    t=np.asarray(types)
    return (t==GAS)|(t==HOT)

def _cells(pos):
    ijk=np.floor(pos/CELL).astype(np.int64)+(1<<20)
    return (ijk[:,0]<<42)|(ijk[:,1]<<21)|ijk[:,2]

def attach(b,params):
    """Allocate u, Z, cool_delay, z_birth. Safe to call twice."""
    n=len(b['type']);gas=is_gas(b['type'])
    Zs=float(params.get('metallicity',1.))*Z_SOLAR
    if 'u' not in b or len(b.get('u',[]))!=n:
        b['u']=np.zeros(n);b['u'][gas]=u_from_T(1e4)
    if 'Z' not in b or len(b.get('Z',[]))!=n:
        b['Z']=np.zeros(n);b['Z'][gas]=Zs
    if 'cool_delay' not in b or len(b.get('cool_delay',[]))!=n:
        b['cool_delay']=np.zeros(n)
    if 'z_birth' not in b or len(b.get('z_birth',[]))!=n:
        b['z_birth']=np.zeros(n)
        alive=(b['type']>=1)&(b['type']<=3);b['z_birth'][alive]=Zs
    b.setdefault('metals_produced',0.);b.setdefault('sn_heat',0.);b.setdefault('shock_heat',0.)

def deposit_heat(b,mass,src,ejecta,params):
    """Laboratory superbubble heat + delayed cooling on neighbouring gas. Mass/Z stay in stellar.py."""
    src=np.asarray(src,dtype=np.int64)
    if len(src)==0 or ejecta<=0:return
    attach(b,params)
    f=float(params.get('sn_feedback',.15))
    msrc=np.maximum(mass[src],1e-30);w=msrc/msrc.sum()
    E=f*.5*float(ejecta)*(200./V_KMS)**2
    b['u'][src]+=E*w/msrc
    b['cool_delay'][src]=np.maximum(b['cool_delay'][src],BLAST_DELAY_MYR)
    b['sn_heat']=float(b.get('sn_heat',0)+E)

def _grid(pos,vel,mass,u,idx):
    keys=_cells(pos[idx]);uniq,inv=np.unique(keys,return_inverse=True);nC=len(uniq)
    m=np.bincount(inv,mass[idx],minlength=nC)
    px=np.bincount(inv,mass[idx]*vel[idx,0],minlength=nC)
    py=np.bincount(inv,mass[idx]*vel[idx,1],minlength=nC)
    pz=np.bincount(inv,mass[idx]*vel[idx,2],minlength=nC)
    U=np.bincount(inv,mass[idx]*u[idx],minlength=nC)
    invm=1./np.maximum(m,1e-30)
    vx,vy,vz=px*invm,py*invm,pz*invm
    uc=U*invm;rho=m/VOL;P=(GAMMA-1.)*rho*np.maximum(uc,U_MIN)
    return dict(uniq=uniq,inv=inv,nC=nC,m=m,vx=vx,vy=vy,vz=vz,uc=uc,rho=rho,P=P,U=U)

def _neighbor_locs(uniq,dx,dy,dz):
    nkey=uniq+(dx<<42)+(dy<<21)+dz
    loc=np.searchsorted(uniq,nkey);nC=len(uniq)
    ok=(loc<nC);loc=np.clip(loc,0,max(nC-1,0))
    if nC:ok&=uniq[loc]==nkey
    return loc,ok

def star_forming(pos,vel,mass,u,types,params):
    """Cold, dense, not-strongly-expanding gas. Used only when ism_enabled."""
    n=len(types);out=np.zeros(n,bool);gas=np.flatnonzero(types==GAS)
    if len(gas)==0:return out
    T,_=temperature(u[gas]);g=_grid(pos,vel,mass,u,gas)
    _Tcell,mucell=temperature(g['uc']);nH=N_H0*g['rho']/np.maximum(mucell,.5)
    div=np.zeros(g['nC'])
    for ax,(dx,dy,dz) in enumerate(((1,0,0),(0,1,0),(0,0,1))):
        loc,ok=_neighbor_locs(g['uniq'],dx,dy,dz)
        vcomp=(g['vx'],g['vy'],g['vz'])[ax]
        if np.any(ok):
            i=np.flatnonzero(ok);j=loc[ok];dv=(vcomp[j]-vcomp[i])/CELL;div[i]+=dv;div[j]+=dv
    n_sf=float(params.get('n_sf',.1));cs=np.sqrt(GAMMA*(GAMMA-1.)*np.maximum(g['uc'],U_MIN))
    expanding=div>(cs/CELL)
    dense_ok=(nH>=n_sf)&(~expanding)
    cell_ok=dense_ok[g['inv']]
    out[gas]=cell_ok&(T<T_SF)
    return out

def _hydro(g,dt,ram_coeff):
    """Momentum-conserving face pressure + visc + ram. Returns (dv per cell, dU thermal)."""
    nC=g['nC'];dp=np.zeros((nC,3));dt=float(dt)
    vx,vy,vz,rho,P,m=g['vx'],g['vy'],g['vz'],g['rho'],g['P'],g['m']
    vcomp=(vx,vy,vz)
    for ax,(dx,dy,dz) in enumerate(((1,0,0),(0,1,0),(0,0,1))):
        loc,ok=_neighbor_locs(g['uniq'],dx,dy,dz)
        i=np.flatnonzero(ok);j=loc[ok] if len(i) else loc
        if len(i):
            vrel=np.column_stack((vx[i]-vx[j],vy[i]-vy[j],vz[i]-vz[j]))
            vn=vrel[:,ax]                       # approaching if left cell outruns right
            closing=np.maximum(vn,0.)
            rho_red=rho[i]*rho[j]/(rho[i]+rho[j]+1e-30)
            Pstar=.5*(P[i]+P[j])+ALPHA_VISC*rho_red*closing*closing
            flux=Pstar*AREA*dt
            dp[i,ax]-=flux;dp[j,ax]+=flux
            if ram_coeff>0:
                speed=np.sqrt(np.sum(vrel*vrel,axis=1)+1e-30)
                Fi=-(ram_coeff*rho_red*speed*AREA*dt)[:,None]*vrel
                dp[i]+=Fi;dp[j]-=Fi
        # vacuum faces: pressure on the missing side is 0, so net -P A n_hat
        locm,okm=_neighbor_locs(g['uniq'],-dx,-dy,-dz)
        miss_plus=~ok;miss_minus=~okm
        dp[miss_plus,ax]-=P[miss_plus]*AREA*dt
        dp[miss_minus,ax]+=P[miss_minus]*AREA*dt
    v_max=.45*CELL/max(dt,1e-9)
    invm=1./np.maximum(m,1e-30)
    dv=dp*invm[:,None]
    spd=np.sqrt(np.sum(dv*dv,axis=1))
    cap=np.minimum(1.,v_max/(spd+1e-30));dv*=cap[:,None]
    vx2,vy2,vz2=vx+dv[:,0],vy+dv[:,1],vz+dv[:,2]
    ke0=.5*m*(vx*vx+vy*vy+vz*vz);ke1=.5*m*(vx2*vx2+vy2*vy2+vz2*vz2)
    dU=ke0-ke1                                 # lost bulk KE → heat; gained KE → cool
    return dv,dU

def _cool(u,nH,Zs,dt_model,speed,delay):
    """Exponential approach to a CIE+heating equilibrium. Delayed particles skip cooling."""
    T,mu=temperature(u)
    Lam=cooling_lambda(T,Zs)
    heat=GAMMA_PE*(.3+.7*np.clip(Zs,0,8))
    net=heat-nH*Lam                              # erg s^-1 per H
    du_phys=net/(mu*M_H)
    du_code=du_phys*DT_PHYS/V2
    t_cool=np.abs(u/(du_code+1e-30*np.sign(du_code+1e-30)))
    frac=1.-np.exp(-float(speed)*float(dt_model)/np.maximum(t_cool,1e-8))
    # Equilibrium u: invert Λ(T)≈heat/n_H on the table, then clamp.
    target=heat/np.maximum(nH,1e-8)
    logT=_LOGT
    lam_tab=10**_LOGP+np.clip(Zs,0,8)[...,None]*10**_LOGZ
    # For each particle, first logT where lam>=target, else hot end.
    ge=lam_tab>=target[...,None]
    # argmax of ge along last axis (first True); if none, last index
    anyge=ge.any(axis=-1)
    idx=np.where(ge,np.arange(len(logT)),len(logT)).min(axis=-1)
    idx=np.where(anyge,np.clip(idx,0,len(logT)-1),len(logT)-1)
    T_eq=10**logT[idx]
    T_eq=np.clip(T_eq,T_FLOOR,T_MAX)
    u_eq=u_from_T(T_eq)
    u_new=u+frac*(u_eq-u)
    hold=delay>0
    u_new=np.where(hold,u,u_new)
    return np.clip(u_new,U_MIN,U_MAX)

def step(q,m,b,params,dt_model):
    """Apply ISM over one leapfrog interval. Mutates q velocities, b['u']/types/delay. Mass unchanged."""
    types=b['type'];attach(b,params)
    gas=np.flatnonzero(is_gas(types))
    if len(gas)==0:return False
    pos=q[:,:3];vel=q[:,3:];u=b['u'];dt=float(dt_model)
    g=_grid(pos,vel,m,u,gas)
    dv,dU=_hydro(g,dt,float(params.get('ram_pressure',1.)))
    # peculiar velocities stay; bulk cell velocity shifts
    vel[gas]+=dv[g['inv']]
    uc_new=(g['U']+dU)/np.maximum(g['m'],1e-30)
    u[gas]+=uc_new[g['inv']]-g['uc'][g['inv']]
    b['shock_heat']=float(b.get('shock_heat',0.)+np.sum(np.maximum(dU,0.)))
    Tcell,mucell=temperature(np.maximum(g['uc'],U_MIN))
    nH_cell=N_H0*g['rho']/np.maximum(mucell,.5)
    nH=nH_cell[g['inv']]
    Zs=b['Z'][gas]/Z_SOLAR
    u[gas]=_cool(np.maximum(u[gas],U_MIN),nH,Zs,dt,float(params.get('cooling_speed',1.)),b['cool_delay'][gas])
    b['cool_delay'][gas]=np.maximum(0.,b['cool_delay'][gas]-dt*MYR_PER_TIME)
    T,_=temperature(u[gas])
    now=types[gas]
    now[(now==GAS)&(T>T_HOT_ON)]=HOT
    now[(now==HOT)&(T<T_HOT_OFF)]=GAS
    types[gas]=now
    u[gas]=np.clip(u[gas],U_MIN,U_MAX);b['u']=u
    return True

def summary_fields(b,m):
    """Extra diagnostics from ISM arrays. Harmless if arrays are missing."""
    n=len(b['type'])
    if 'u' not in b or len(b['u'])!=n:return {}
    gas=is_gas(b['type']);mg=m[gas]
    if not np.any(gas):return dict(cold_gas_mass=0.,hot_gas_mass=0.,mean_temperature=0.,mean_metallicity=0.,blast_delayed=0)
    T,_=temperature(b['u'][gas]);w=np.maximum(mg,0)
    cold=b['type']==GAS;hot=b['type']==HOT
    zsun=(b['Z'][gas]/Z_SOLAR)
    return dict(
        cold_gas_mass=float(np.sum(m[cold])),hot_gas_mass=float(np.sum(m[hot])),
        mean_temperature=float(np.average(T,weights=w) if np.sum(w)>0 else 0.),
        mean_metallicity=float(np.average(zsun,weights=w) if np.sum(w)>0 else 0.),
        blast_delayed=int(np.sum((b['cool_delay']>0)&gas)),
        metals_produced=float(b.get('metals_produced',0.)),
        sn_heat=float(b.get('sn_heat',0.)),shock_heat=float(b.get('shock_heat',0.)))
