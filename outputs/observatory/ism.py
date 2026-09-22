# AGENT MAP: laboratory two-phase ISM on the existing O(N) density grid.
# Not SPH, not a Riemann solver, not GADGET. Gas is still superparticles.
# Forces are real (pressure, ram, snowplow, cloud drag) and feed REBOUND velocities.
# Cooling uses a CIE-like Λ(T,Z). Ionization fraction x_e is carried and can lag.
# Metals diffuse across cell faces. Young stars add local FUV, shut off when shielded.
# Star formation may only consume cold, dense, non-expanding gas.
# Isolated collisionless ICs are unchanged because this module never runs when lifecycle is off.
"""Grid ISM: cooling, pressure, ram, snowplow, cloud drag, metal mixing, local FUV."""
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
# Laboratory UV/turbulent heating floor (erg s^-1 per H). Not a Haardt–Madau background.
GAMMA_PE=2.0e-22
# Background photoionization rate (s^-1). Shielded the same way as the heat.
GAMMA_ION=3.0e-14
N_SHIELD=1.0                 # cm^-3; heating and ionizing flux fall above this
L_REF=40.                    # Msun of young stars in/near the cell for a full FUV boost
FUV_AGE_MYR=30.
SNOW_V_KMS=200.              # laboratory snowplow scale, same as the thermal dump
SNOW_CAP=1.2                 # code velocity cap on one feedback event (~144 km/s)
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

U_MIN=float(u_from_T(T_FLOOR));U_MAX=float(u_from_T(T_MAX));U_COLD=float(u_from_T(1.0e3))

def mu_of_x(x):
    """Neutral μ=1.4 at x=0, ionized μ=0.62 at x=1. x is n_e/n_H."""
    x=np.clip(np.asarray(x,dtype=np.float64),0.,1.)
    return 1.4*(1.-x)+.62*x

def thermal_state(u,x):
    """(T[K], μ) from specific energy and the carried electron fraction."""
    mu=mu_of_x(x)
    T=T_PER_U*mu*np.maximum(np.asarray(u,dtype=np.float64),1e-18)
    return T,mu

def k_collisional(T):
    """Cen 1992 hydrogen collisional ionization, cm^3 s^-1."""
    T=np.clip(np.asarray(T,dtype=np.float64),1e2,1e9)
    return 5.85e-11*np.sqrt(T)*np.exp(-157809.1/T)/(1.+np.sqrt(T/1e5))

def alpha_recomb(T):
    """Cen 1992 case-B-like recombination, cm^3 s^-1."""
    T=np.clip(np.asarray(T,dtype=np.float64),1e2,1e9)
    return 8.4e-11*T**-0.5*(T/1e3)**-0.2/(1.+(T/1e6)**0.7)

def x_equilibrium(T,nH,Gamma):
    """Coronal + photo equilibrium of dx/dt = n_H[x(1-x)C - x^2 α] + (1-x)Γ."""
    C=k_collisional(T);a=alpha_recomb(T)
    nH=np.maximum(np.asarray(nH,dtype=np.float64),0.)
    Gamma=np.maximum(np.asarray(Gamma,dtype=np.float64),0.)
    A=nH*(C+a);B=Gamma-nH*C
    disc=B*B+4.*A*Gamma
    x=np.where(A>1e-30,(-B+np.sqrt(np.maximum(disc,0.)))/(2.*A),np.where(Gamma>0.,1.,0.))
    return np.clip(x,0.,1.)

def relax_ionization(x,nH,T,Gamma,dt_sec):
    """Approach equilibrium on the local ionization time. Dense gas snaps; diffuse gas lags."""
    x_eq=x_equilibrium(T,nH,Gamma)
    C=k_collisional(T);a=alpha_recomb(T)
    rate=np.maximum(nH,0.)*(C+a)+np.maximum(Gamma,0.)
    frac=1.-np.exp(-np.clip(float(dt_sec)*rate,0.,60.))
    return np.clip(np.asarray(x,dtype=np.float64)+frac*(x_eq-x),0.,1.),x_eq,frac

def radiation_field(nH,Zs,star_L,params):
    """Heat (erg s^-1 per H), photoionization rate, shielding, and FUV multiplier."""
    fuv=float(params.get('fuv_heating',1.))
    star_L=np.maximum(np.asarray(star_L,dtype=np.float64),0.)
    presence=star_L/(star_L+L_REF)
    mult=1.+fuv*presence
    shield=1./(1.+(np.asarray(nH,dtype=np.float64)/N_SHIELD)**2)
    zfac=.3+.7*np.clip(np.asarray(Zs,dtype=np.float64),0.,8.)
    heat=GAMMA_PE*zfac*shield*mult
    Gamma=GAMMA_ION*shield*mult
    return heat,Gamma,shield,mult

def is_gas(types):
    t=np.asarray(types)
    return (t==GAS)|(t==HOT)

def _cells(pos):
    ijk=np.floor(pos/CELL).astype(np.int64)+(1<<20)
    return (ijk[:,0]<<42)|(ijk[:,1]<<21)|ijk[:,2]

def attach(b,params):
    """Allocate u, Z, x, cool_delay, z_birth. Safe to call twice. Does not consume RNG."""
    n=len(b['type']);gas=is_gas(b['type'])
    Zs=float(params.get('metallicity',1.))*Z_SOLAR
    if 'x' not in b or len(b.get('x',[]))!=n:
        b['x']=np.zeros(n)
        if np.any(gas):
            xe=float(x_equilibrium(np.array([1e4]),np.array([0.3]),np.array([GAMMA_ION]))[0])
            b['x'][gas]=xe
    if 'u' not in b or len(b.get('u',[]))!=n:
        b['u']=np.zeros(n)
        if np.any(gas):b['u'][gas]=1e4/(T_PER_U*mu_of_x(b['x'][gas]))
    if 'Z' not in b or len(b.get('Z',[]))!=n:
        b['Z']=np.zeros(n);b['Z'][gas]=Zs
    if 'cool_delay' not in b or len(b.get('cool_delay',[]))!=n:
        b['cool_delay']=np.zeros(n)
    if 'z_birth' not in b or len(b.get('z_birth',[]))!=n:
        b['z_birth']=np.zeros(n)
        alive=(b['type']>=1)&(b['type']<=3);b['z_birth'][alive]=Zs
    b.setdefault('metals_produced',0.);b.setdefault('sn_heat',0.);b.setdefault('shock_heat',0.)
    b.setdefault('cloud_heat',0.);b.setdefault('sn_momentum',0.);b.setdefault('x_lag',0.)

def deposit_heat(b,mass,src,ejecta,params):
    """Laboratory superbubble heat + delayed cooling on neighbouring gas. Mass/Z stay in stellar.py."""
    src=np.asarray(src,dtype=np.int64)
    if len(src)==0 or ejecta<=0:return 0.
    attach(b,params)
    f=float(params.get('sn_feedback',.15))
    msrc=np.maximum(mass[src],1e-30);w=msrc/msrc.sum()
    E=f*.5*float(ejecta)*(SNOW_V_KMS/V_KMS)**2
    b['u'][src]+=E*w/msrc
    b['cool_delay'][src]=np.maximum(b['cool_delay'][src],BLAST_DELAY_MYR)
    b['sn_heat']=float(b.get('sn_heat',0)+E)
    return float(E)

def deposit_feedback(b,mass,vel,pos,src,origin,reaction,ejecta,params):
    """Thermal dump plus a momentum-conserving snowplow. Returns True if velocities changed."""
    deposit_heat(b,mass,src,ejecta,params)
    f=float(params.get('sn_momentum',.4))
    src=np.asarray(src,dtype=np.int64)
    if f<=0 or ejecta<=0 or len(src)==0 or vel is None:return False
    origin=np.asarray(origin,dtype=np.float64)
    hat=pos[src]-origin
    r=np.linalg.norm(hat,axis=1)
    hat=hat/np.maximum(r[:,None],1e-8)
    bad=r<1e-6
    if np.any(bad):
        basis=np.array([[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]])
        hat[bad]=basis[np.asarray(src)[bad]%3]
    msrc=np.maximum(mass[src],1e-30)
    w=msrc/msrc.sum()
    P=f*float(ejecta)*(SNOW_V_KMS/V_KMS)
    dv=hat*(w*P)[:,None]/msrc[:,None]
    m_reac=max(float(mass[reaction]),1e-30)
    dp_tot=(msrc[:,None]*dv).sum(axis=0)
    dv_reac=dp_tot/m_reac
    peak=max(float(np.max(np.linalg.norm(dv,axis=1))),float(np.linalg.norm(dv_reac)))
    scale=min(1.,SNOW_CAP/peak) if peak>0 else 1.
    vel[src]+=dv*scale
    vel[reaction]-=dv_reac*scale
    # Scalar impulse delivered to the gas. A symmetric shell has ~0 net momentum and still moves.
    b['sn_momentum']=float(b.get('sn_momentum',0.)+float(np.sum(msrc*np.linalg.norm(dv,axis=1)))*scale)
    return True

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

def star_forming(pos,vel,mass,u,types,params,x=None):
    """Cold, dense, not-strongly-expanding gas. Used only when ism_enabled."""
    n=len(types);out=np.zeros(n,bool);gas=np.flatnonzero(types==GAS)
    if len(gas)==0:return out
    if x is None:T,_=temperature(u[gas])
    else:T,_=thermal_state(u[gas],np.asarray(x,dtype=np.float64)[gas])
    g=_grid(pos,vel,mass,u,gas)
    if x is None:
        _Tcell,mucell=temperature(g['uc'])
    else:
        mu_p=mu_of_x(np.asarray(x,dtype=np.float64)[gas])
        mucell=np.bincount(g['inv'],mass[gas]*mu_p,minlength=g['nC'])/np.maximum(g['m'],1e-30)
    nH=N_H0*g['rho']/np.maximum(mucell,.5)
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

def dissipate_peculiar(vel,mass,u,idx,g,dt,coeff):
    """Pull peculiar speeds toward the post-kick bulk velocity. Lost KE becomes heat. Momentum stays."""
    if coeff<=0 or len(idx)==0:return 0.
    inv=g['inv']
    vbulk=np.column_stack((g['vx'],g['vy'],g['vz']))[inv]
    v=vel[idx];m=mass[idx];vpec=v-vbulk
    epec=np.bincount(inv,m*np.sum(vpec*vpec,axis=1),minlength=g['nC'])
    sig=np.sqrt(np.maximum(epec/np.maximum(g['m'],1e-30),0.))
    frac=(1.-np.exp(-float(coeff)*float(dt)*sig/(CELL+1e-9)))[inv]
    vnew=vbulk+vpec*(1.-frac)[:,None]
    dke=np.maximum(.5*m*(np.sum(v*v,axis=1)-np.sum(vnew*vnew,axis=1)),0.)
    u[idx]+=dke/np.maximum(m,1e-30)
    vel[idx]=vnew
    return float(dke.sum())

def diffuse_metals(mass,Z,idx,g,dt,coeff):
    """Conservative metal exchange across faces. Intra-cell differences are kept."""
    if coeff<=0 or g['nC']<2:return
    inv=g['inv'];mcell=g['m']
    Mz=np.bincount(inv,mass[idx]*Z[idx],minlength=g['nC'])
    Z0=Mz/np.maximum(mcell,1e-30)
    cur=Mz.copy();frac=1.-np.exp(-float(coeff)*float(dt))
    for dx,dy,dz in ((1,0,0),(0,1,0),(0,0,1)):
        loc,ok=_neighbor_locs(g['uniq'],dx,dy,dz)
        i=np.flatnonzero(ok)
        if len(i)==0:continue
        j=loc[i]
        Zc=cur/np.maximum(mcell,1e-30)
        red=mcell[i]*mcell[j]/np.maximum(mcell[i]+mcell[j],1e-30)
        flux=.5*frac*(Zc[i]-Zc[j])*red
        flux=np.minimum(flux,.45*np.maximum(cur[i],0.))
        flux=np.maximum(flux,-.45*np.maximum(cur[j],0.))
        cur[i]-=flux;cur[j]+=flux
    dZ=(cur/np.maximum(mcell,1e-30)-Z0)[inv]
    Z[idx]=np.clip(Z[idx]+dZ,0.,.5)

def local_star_light(pos,types,m_star,age,gas_uniq):
    """Young massive-star light (Msun) seen by each gas cell, diluted onto the six face neighbors."""
    acc=np.zeros(len(gas_uniq))
    if len(gas_uniq)==0:return acc
    young=np.flatnonzero((m_star>=8.)&(age>=0.)&(age<FUV_AGE_MYR)&((types==1)|(types==2)|(types==3)))
    if len(young)==0:return acc
    keys=_cells(pos[young]);L=np.asarray(m_star[young],dtype=np.float64)
    for dx,dy,dz,w in ((0,0,0,1.),(1,0,0,.4),(-1,0,0,.4),(0,1,0,.4),(0,-1,0,.4),(0,0,1,.4),(0,0,-1,.4)):
        nkey=keys+(dx<<42)+(dy<<21)+int(dz)
        loc=np.searchsorted(gas_uniq,nkey)
        ok=loc<len(gas_uniq);loc=np.clip(loc,0,max(len(gas_uniq)-1,0))
        if len(gas_uniq):ok&=gas_uniq[loc]==nkey
        if np.any(ok):np.add.at(acc,loc[ok],w*L[ok])
    return acc

def _cool(u,nH,Zs,dt_model,speed,delay,heat,x,x_eq,shield):
    """Approach a shielded CIE equilibrium. Under-ionized gas has weaker metal lines. Delayed parcels skip cooling."""
    T,mu=thermal_state(u,x)
    logT=np.log10(np.clip(T,1e2,1e9))
    Lam_p=10**np.interp(logT,_LOGT,_LOGP)
    Lam_z=np.clip(Zs,0.,8.)*10**np.interp(logT,_LOGT,_LOGZ)
    lag=np.clip(np.asarray(x,dtype=np.float64)/np.maximum(x_eq,1e-4),0.,1.)
    Lam=Lam_p+Lam_z*lag
    net=np.asarray(heat,dtype=np.float64)-nH*Lam
    du_phys=net/(mu*M_H)
    du_code=du_phys*DT_PHYS/V2
    t_cool=np.abs(u/(du_code+1e-30*np.sign(du_code+1e-30)))
    frac=1.-np.exp(-float(speed)*float(dt_model)/np.maximum(t_cool,1e-8))
    target=np.asarray(heat,dtype=np.float64)/np.maximum(nH,1e-8)
    zfac=np.clip(Zs,0.,8.)*lag
    lam_tab=10**_LOGP+zfac[...,None]*10**_LOGZ
    ge=lam_tab>=target[...,None]
    anyge=ge.any(axis=-1)
    idx=np.where(ge,np.arange(len(_LOGT)),len(_LOGT)).min(axis=-1)
    idx=np.where(anyge,np.clip(idx,0,len(_LOGT)-1),len(_LOGT)-1)
    floor_T=np.where(np.asarray(shield)<.25,1.0e3,T_FLOOR)
    T_eq=np.clip(10**_LOGT[idx],floor_T,T_MAX)
    u_eq=T_eq/(T_PER_U*mu)
    u_new=np.where(np.asarray(delay)>0,u,u+frac*(u_eq-u))
    u_floor=floor_T/(T_PER_U*mu)
    return np.clip(np.maximum(u_new,u_floor),U_COLD,U_MAX)

def step(q,m,b,params,dt_model):
    """ISM over one leapfrog interval. Mutates gas velocities, u, x, Z and hot/cold type. Mass unchanged."""
    types=b['type'];attach(b,params)
    gas=np.flatnonzero(is_gas(types))
    if len(gas)==0:return False
    pos=q[:,:3];vel=q[:,3:];u=b['u'];dt=float(dt_model)
    g=_grid(pos,vel,m,u,gas)
    dv,dU=_hydro(g,dt,float(params.get('ram_pressure',1.)))
    vel[gas]+=dv[g['inv']]
    g['vx']=g['vx']+dv[:,0];g['vy']=g['vy']+dv[:,1];g['vz']=g['vz']+dv[:,2]
    uc_new=(g['U']+dU)/np.maximum(g['m'],1e-30)
    u[gas]+=uc_new[g['inv']]-g['uc'][g['inv']]
    b['shock_heat']=float(b.get('shock_heat',0.)+np.sum(np.maximum(dU,0.)))
    b['cloud_heat']=float(b.get('cloud_heat',0.)+dissipate_peculiar(vel,m,u,gas,g,dt,float(params.get('cloud_dissipation',1.))))
    diffuse_metals(m,b['Z'],gas,g,dt,float(params.get('metal_diffusion',.6)))
    mu_p=mu_of_x(b['x'][gas])
    mu_c=np.bincount(g['inv'],m[gas]*mu_p,minlength=g['nC'])/np.maximum(g['m'],1e-30)
    nH= (N_H0*g['rho']/np.maximum(mu_c,.5))[g['inv']]
    starL=local_star_light(pos,types,b['m_star'],b['age'],g['uniq'])
    Zs=b['Z'][gas]/Z_SOLAR
    heat,Gamma,shield,_mult=radiation_field(nH,Zs,starL[g['inv']],params)
    Tnow,_=thermal_state(u[gas],b['x'][gas])
    if bool(params.get('noneq_ionization',True)):
        x_new,x_eq,_frac=relax_ionization(b['x'][gas],nH,Tnow,Gamma,dt*DT_PHYS)
        b['x'][gas]=x_new
    else:
        x_eq=x_equilibrium(Tnow,nH,Gamma);b['x'][gas]=x_eq
    w=np.maximum(m[gas],0.)
    b['x_lag']=float(np.average(np.abs(b['x'][gas]-x_eq),weights=w) if np.sum(w)>0 else 0.)
    u[gas]=_cool(np.maximum(u[gas],1e-18),nH,Zs,dt,float(params.get('cooling_speed',1.)),b['cool_delay'][gas],heat,b['x'][gas],x_eq,shield)
    b['cool_delay'][gas]=np.maximum(0.,b['cool_delay'][gas]-dt*MYR_PER_TIME)
    T,_=thermal_state(u[gas],b['x'][gas])
    now=types[gas]
    now[(now==GAS)&(T>T_HOT_ON)]=HOT
    now[(now==HOT)&(T<T_HOT_OFF)]=GAS
    types[gas]=now
    u[gas]=np.clip(u[gas],U_COLD,U_MAX);b['u']=u
    return True

def summary_fields(b,m):
    """Extra diagnostics from ISM arrays. Harmless if arrays are missing."""
    n=len(b['type'])
    if 'u' not in b or len(b['u'])!=n:return {}
    gas=is_gas(b['type']);mg=m[gas]
    if not np.any(gas):return dict(cold_gas_mass=0.,hot_gas_mass=0.,mean_temperature=0.,mean_metallicity=0.,blast_delayed=0,mean_electron_fraction=0.,metal_std=0.)
    x=b['x'][gas] if 'x' in b and len(b['x'])==n else np.full(int(np.sum(gas)),.2)
    T,_=thermal_state(b['u'][gas],x);w=np.maximum(mg,0)
    cold=b['type']==GAS;hot=b['type']==HOT
    zsun=(b['Z'][gas]/Z_SOLAR)
    zmean=float(np.average(zsun,weights=w) if np.sum(w)>0 else 0.)
    zvar=float(np.average((zsun-zmean)**2,weights=w) if np.sum(w)>0 else 0.)
    return dict(
        cold_gas_mass=float(np.sum(m[cold])),hot_gas_mass=float(np.sum(m[hot])),
        mean_temperature=float(np.average(T,weights=w) if np.sum(w)>0 else 0.),
        mean_metallicity=zmean,metal_std=float(np.sqrt(max(zvar,0.))),
        mean_electron_fraction=float(np.average(x,weights=w) if np.sum(w)>0 else 0.),
        x_lag=float(b.get('x_lag',0.)),
        blast_delayed=int(np.sum((b['cool_delay']>0)&gas)),
        metals_produced=float(b.get('metals_produced',0.)),
        sn_heat=float(b.get('sn_heat',0.)),shock_heat=float(b.get('shock_heat',0.)),
        cloud_heat=float(b.get('cloud_heat',0.)),sn_momentum=float(b.get('sn_momentum',0.)))
