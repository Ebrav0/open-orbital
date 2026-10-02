# AGENT MAP: collisionless baryon lifecycle. Gas -> protostar -> MS -> giant -> WD/NS/BH.
# Gravity always uses the current REBOUND slot masses; this module changes those masses.
# Clock uses m_star (Msun). Force uses slot mass (code units). N never changes.
# Not hydro, not MESA. lifecycle_speed is a laboratory clock, not a calibration.
# Disk occupancy is disk_mask, not a global prefix — required for concatenated [disk|halo|smbh] galaxies.
"""Stellar birth, growth and death for the observatory galaxy model."""
import numpy as np

# Galaxy code units: G=1, mass 1e10 Msun, length 3 kpc. Derived time and velocity units.
MYR_PER_TIME=24.50          # one code time unit in Myr
V_KMS=119.7                 # one code velocity unit in km/s
GAS,PROTO,MS,GIANT,WD,NS,BH,HALO,SMBH=range(9)
TYPE_NAMES=['gas','protostar','main_sequence','giant','white_dwarf','neutron_star','black_hole','halo','smbh']
CELL=.15                    # density grid cell in code lengths (~450 pc)

def kroupa_masses(rng,n,mmin=.08,mmax=100.):
    """Sample n stellar masses (Msun) from a Kroupa (2001) IMF by inverse CDF on the broken power law."""
    mmin=max(float(mmin),.01);mmax=max(float(mmax),mmin*1.01)
    edges=np.array([mmin,.08,.5,mmax]);slopes=np.array([.3,1.3,2.3])
    keep=[];lo=mmin
    segs=[]
    for i in range(3):
        a,b=edges[i],edges[i+1]
        if b<=lo or a>=mmax:continue
        a=max(a,lo);b=min(b,mmax)
        if b<=a:continue
        segs.append((a,b,slopes[i]))
    # Continuity constants so the pdf is continuous across breaks.
    consts=[];c=1.
    for i,(a,b,s) in enumerate(segs):
        if i:c*=(a**-segs[i-1][2])/(a**-s)
        consts.append(c)
    weights=np.array([c*(b**(1-s)-a**(1-s))/(1-s) for (a,b,s),c in zip(segs,consts)]);weights/=weights.sum()
    seg=rng.choice(len(segs),size=n,p=weights);u=rng.random(n);out=np.empty(n)
    for i,(a,b,s) in enumerate(segs):
        mask=seg==i
        if not np.any(mask):continue
        out[mask]=(a**(1-s)+u[mask]*(b**(1-s)-a**(1-s)))**(1/(1-s))
    return out

def lifetime_myr(m_star):
    """Main-sequence plus giant lifetime in Myr: 10 Gyr (m/Msun)^-2.5, clipped to [3, 20000]."""
    m=np.maximum(np.asarray(m_star,dtype=np.float64),1e-3)
    return np.clip(1e4*m**-2.5,3.,2e4)

def prems_myr(m_star):
    return np.clip(.05*lifetime_myr(m_star),.1,3.)

def remnant_of(m_star):
    """Return (remnant type, remnant mass in Msun) for an evolutionary mass in Msun."""
    m=np.asarray(m_star,dtype=np.float64)
    rtype=np.where(m<8,WD,np.where(m<20,NS,BH)).astype(np.uint8)
    rmass=np.where(m<8,np.minimum(.6+.05*np.maximum(m-1,0),1.3),np.where(m<20,1.4,np.clip(.1*m,3.,15.)))
    return rtype,rmass

def _disk_slices(disk_mask):
    """Contiguous True runs in disk_mask — one per galaxy disk in the concatenated layout."""
    dm=np.asarray(disk_mask,dtype=bool)
    if not np.any(dm):return []
    padded=np.concatenate([[False],dm,[False]])
    d=np.diff(padded.astype(np.int8))
    return list(zip(np.flatnonzero(d==1),np.flatnonzero(d==-1)))

def new_baryons(rng,n,disk_mask,params):
    """Initial lifecycle arrays. Each galaxy disk slice gets its own gas prefix; the rest are an aged MS/giant population."""
    disk_mask=np.asarray(disk_mask,dtype=np.uint8)
    if disk_mask.shape!=(n,):raise ValueError('disk_mask must have length n')
    types=np.full(n,HALO,np.uint8);m_star=np.zeros(n);age=np.zeros(n);birth=np.zeros(n)
    for a,b in _disk_slices(disk_mask):
        nd=b-a;ng=int(round(nd*float(params['gas_fraction'])));types[a:a+ng]=GAS;ns=nd-ng
        if ns>0:
            ms=kroupa_masses(rng,ns,params['imf_mmin'],params['imf_mmax']);tms=lifetime_myr(ms)
            cand=rng.uniform(0,8000,ns);alive=cand<.95*tms
            ages=np.where(alive,cand,tms*rng.uniform(.05,.95,ns))
            types[a+ng:b]=np.where(ages>=.9*tms,GIANT,MS);m_star[a+ng:b]=ms;age[a+ng:b]=ages;birth[a+ng:b]=-ages/MYR_PER_TIME
    return dict(type=types,age=age,m_star=m_star,birth_time=birth,disk_mask=disk_mask.copy(),disk_count=int(np.sum(disk_mask)),debt=0.,born_mass=0.,born_window_myr=0.,supernovae=0,deaths=0,births=0,failed_return=0.)

def kroupa_pdf(m):
    """Kroupa (2001) IMF dN/dm, continuous at 0.08 and 0.5 Msun, unnormalized."""
    m=np.asarray(m,dtype=np.float64)
    return np.where(m<.08,(m/.08)**-.3,np.where(m<.5,(m/.08)**-1.3,(.5/.08)**-1.3*(m/.5)**-2.3))

SSP_AGES=np.concatenate(([0.],np.geomspace(.1,4e4,3000)))   # Myr

def ssp_tables(mmin=.08,mmax=100.):
    """Model revision 6: a star particle is a simple stellar population (SSP), not one star. Per Msun formed, the
    mass returned to gas and the number of core-collapse supernovae (m >= 8 Msun) by each age in SSP_AGES, from the
    same Kroupa IMF, lifetime law and remnant masses the single-star lifecycle uses. Stars whose lifetime hits the
    20 Gyr clip never die here."""
    mmin=max(float(mmin),.01);mmax=max(float(mmax),mmin*1.01)
    m=np.geomspace(mmin,mmax,6000);xi=kroupa_pdf(m);norm=np.trapezoid(m*xi,m)
    tau=lifetime_myr(m);_,rmass=remnant_of(m);dies=tau<2e4
    order=np.argsort(tau);t=tau[order]
    w=(xi*np.gradient(m))[order]/norm
    ret=np.cumsum(np.where(dies[order],np.maximum(m[order]-rmass[order],0.)*w,0.))
    sn=np.cumsum(np.where(dies[order]&(m[order]>=8),w,0.))
    idx=np.searchsorted(t,SSP_AGES,side='right')
    pad=lambda c:np.concatenate(([0.],c))[idx]
    return pad(ret),pad(sn)

def new_baryons_ssp(rng,n,disk_mask,params,mass):
    """Model revision 6 lifecycle arrays. Gas as before; each disk star particle is a population with age drawn from
    a constant 8 Gyr history. m_star holds its initial mass (code units) so its present mass matches the ICs."""
    disk_mask=np.asarray(disk_mask,dtype=np.uint8)
    if disk_mask.shape!=(n,):raise ValueError('disk_mask must have length n')
    ret,_=ssp_tables(params['imf_mmin'],params['imf_mmax'])
    types=np.full(n,HALO,np.uint8);m_star=np.zeros(n);age=np.zeros(n);birth=np.zeros(n)
    for a,b in _disk_slices(disk_mask):
        nd=b-a;ng=int(round(nd*float(params['gas_fraction'])));types[a:a+ng]=GAS;ns=nd-ng
        if ns>0:
            ages=rng.uniform(0,8000,ns);types[a+ng:b]=np.where(ages<10.,PROTO,MS)
            age[a+ng:b]=ages;birth[a+ng:b]=-ages/MYR_PER_TIME
            m_star[a+ng:b]=mass[a+ng:b]/(1-np.interp(ages,SSP_AGES,ret))
    return dict(type=types,age=age,m_star=m_star,birth_time=birth,disk_mask=disk_mask.copy(),disk_count=int(np.sum(disk_mask)),debt=0.,born_mass=0.,born_window_myr=0.,supernovae=0,deaths=0,births=0,failed_return=0.,
        ssp=True,pending=np.zeros(n),sn_total=0.,p_delivered=0.,p_unused=0.,returned=0.)

def save_baryons(path,b):
    mask=b.get('disk_mask')
    if mask is None:
        mask=np.zeros(len(b['type']),np.uint8);mask[:int(b['disk_count'])]=1
    extra={}
    if b.get('ssp'):extra=dict(pending=b['pending'],ssp=np.array([b['sn_total'],b['p_delivered'],b['p_unused'],b['returned']],dtype=np.float64))
    np.savez(path,type=b['type'],age=b['age'],m_star=b['m_star'],birth_time=b['birth_time'],disk_mask=np.asarray(mask,dtype=np.uint8),scalars=np.array([b['disk_count'],b['debt'],b['born_mass'],b['born_window_myr'],b['supernovae'],b['deaths'],b['births'],b['failed_return']],dtype=np.float64),**extra)

def load_baryons(path):
    z=np.load(path);s=z['scalars'];n=len(z['type']);disk_count=int(s[0])
    if 'disk_mask' in z.files:mask=z['disk_mask'].astype(np.uint8)
    else:
        mask=np.zeros(n,np.uint8);mask[:disk_count]=1
    out=dict(type=z['type'].astype(np.uint8),age=z['age'],m_star=z['m_star'],birth_time=z['birth_time'],disk_mask=mask,disk_count=disk_count,debt=float(s[1]),born_mass=float(s[2]),born_window_myr=float(s[3]),supernovae=int(s[4]),deaths=int(s[5]),births=int(s[6]),failed_return=float(s[7]))
    if 'ssp' in z.files:
        e=z['ssp'];out.update(ssp=True,pending=z['pending'],sn_total=float(e[0]),p_delivered=float(e[1]),p_unused=float(e[2]),returned=float(e[3]))
    return out

def _cells(pos):
    """Integer cell key per row; keys are sortable int64 from a shifted 3D grid."""
    ijk=np.floor(pos/CELL).astype(np.int64)+(1<<20)
    return (ijk[:,0]<<42)|(ijk[:,1]<<21)|ijk[:,2]

def _neighbour_gas(key,gas_keys_sorted,gas_order):
    """Indices (into gas arrays) of gas in the same cell, else the 26 surrounding cells."""
    def lookup(k):
        lo=np.searchsorted(gas_keys_sorted,k,'left');hi=np.searchsorted(gas_keys_sorted,k,'right');return gas_order[lo:hi]
    found=lookup(key)
    if len(found):return found
    out=[]
    for dx in (-1,0,1):
        for dy in (-1,0,1):
            for dz in (-1,0,1):
                if dx==dy==dz==0:continue
                out.append(lookup(key+(dx<<42)+(dy<<21)+dz))
    return np.concatenate(out) if out else found

def step(sim,b,params,dt_model,seed):
    """Advance the lifecycle by one gravity step. Mutates REBOUND masses and (for kicks) velocities in place."""
    speed=float(params['lifecycle_speed']);dt_myr=dt_model*MYR_PER_TIME*speed
    types=b['type'];age=b['age'];m_star=b['m_star']
    rng=np.random.default_rng([int(seed)&0xffffffff,int(sim.steps_done)&0xffffffff])
    n=sim.N;q=np.empty((n,6));m=np.empty(n);sim.serialize_particle_data(xyzvxvyvz=q,m=m)
    pos=q[:,:3];vel=q[:,3:].copy();dm=np.zeros(n);dv=None;changed=False
    # Revision 5: moved mass carries its momentum (a perfectly inelastic merge for the receiver). Revision 4 moved
    # mass at the receiver's velocity, which does not conserve momentum; kept only so older runs resume unchanged.
    carry=int(params.get('revision',4))>=5;dp=np.zeros((n,3)) if carry else None
    gas_idx=np.flatnonzero(types==GAS)
    gas_keys=None;gas_order=None
    if len(gas_idx):
        keys=_cells(pos[gas_idx]);gas_order=np.argsort(keys,kind='stable');gas_keys=keys[gas_order]
    # ---- aging ----
    alive=(types>=PROTO)&(types<=GIANT)
    age[alive]+=dt_myr
    tms=lifetime_myr(np.where(alive,m_star,1.))
    # protostar -> MS
    grow=np.flatnonzero(types==PROTO)
    if len(grow) and len(gas_idx) and float(params['grow_rate'])>0:
        rate=float(params['grow_rate'])*dt_myr
        pkeys=_cells(pos[grow])
        for gi,key in zip(grow,pkeys):
            nb=_neighbour_gas(key,gas_keys,gas_order)
            if not len(nb):continue
            src=gas_idx[nb];avail=m[src]+dm[src];want=min(float(avail.sum())*.5,m[gi]*rate)
            if want<=0:continue
            take=avail/avail.sum()*want;dm[src]-=take;dm[gi]+=want;changed=True
            if carry:
                mv=take[:,None]*vel[src];dp[src]-=mv;dp[gi]+=mv.sum(0)
    done=grow[age[grow]>=prems_myr(m_star[grow])] if len(grow) else grow
    types[done]=MS
    # MS -> giant
    ms_idx=np.flatnonzero(types==MS);to_giant=ms_idx[age[ms_idx]>=.9*tms[ms_idx]];types[to_giant]=GIANT
    # giant -> remnant
    giants=np.flatnonzero(types==GIANT);dying=giants[age[giants]>=tms[giants]]
    kick_kms=float(params['sn_kick_kms'])
    if len(dying):
        rtype,rmass=remnant_of(m_star[dying]);frac=np.clip(rmass/np.maximum(m_star[dying],1e-6),0,1)
        slot=m[dying]+dm[dying];ejecta=slot*(1-frac)
        dkeys=_cells(pos[dying]) if len(gas_idx) else None
        kicks=[]
        for j,(di,e) in enumerate(zip(dying,ejecta)):
            if e>0:
                nb=_neighbour_gas(dkeys[j],gas_keys,gas_order) if len(gas_idx) else np.empty(0,np.int64)
                if len(nb):
                    src=gas_idx[nb];dm[src]+=e/len(src);dm[di]-=e
                    if carry:dp[src]+=e/len(src)*vel[di];dp[di]-=e*vel[di]
                else:b['failed_return']+=float(e)
            if rtype[j] in (NS,BH) and kick_kms>0:kicks.append(di)
        types[dying]=rtype;b['deaths']+=len(dying);b['supernovae']+=int(np.sum(m_star[dying]>=8));changed=True
        if kicks:
            kicks=np.array(kicks);dirs=rng.normal(size=(len(kicks),3));dirs/=np.linalg.norm(dirs,axis=1)[:,None]
            q[kicks,3:]+=dirs*(kick_kms/V_KMS);dv=True
    # ---- birth ----
    gas_mass=float(np.sum(m[gas_idx]+dm[gas_idx])) if len(gas_idx) else 0.
    t_sf_myr=max(float(params['t_sf'])*1000.,1.)
    if gas_mass>0:
        b['debt']+=gas_mass/t_sf_myr*dt_myr   # dt_myr already carries lifecycle_speed
        slot_mass=gas_mass/len(gas_idx);k=int(min(b['debt']//slot_mass,len(gas_idx)))
        if k>0:
            cell_index=np.searchsorted(gas_keys,_cells(pos[gas_idx]))
            counts=np.bincount(cell_index,minlength=len(gas_keys)+1);density=counts[cell_index].astype(np.float64)
            rank=np.argsort(np.argsort(density))/max(len(density)-1,1)
            bias=float(params['sf_density_bias']);score=bias*rank+(1-bias)*rng.random(len(density))
            pick=gas_idx[np.argpartition(-score,k-1)[:k]] if k<len(gas_idx) else gas_idx
            born_mass=float(np.sum(m[pick]+dm[pick]));b['debt']-=born_mass;b['born_mass']+=born_mass;b['births']+=len(pick)
            ms=kroupa_masses(rng,len(pick),params['imf_mmin'],params['imf_mmax'])
            m_star[pick]=ms;age[pick]=0.;b['birth_time'][pick]=sim.t
            types[pick]=np.where(ms>=2.,PROTO,MS)
    b['born_window_myr']+=dt_myr
    # ---- write back ----
    if changed and np.any(dm):
        if carry:
            new=m+dm;ok=(new>0)&np.any(dp!=0,axis=1)
            if np.any(ok):
                # A donor keeps its velocity: (m v - t v)/(m - t) = v. Kicks (already in q) are added on top.
                q[ok,3:]+=(m[ok,None]*vel[ok]+dp[ok])/new[ok,None]-vel[ok];dv=True
        m+=dm;m[:]=np.maximum(m,0.)
        sim.set_serialized_particle_data(m=m)
    if dv:sim.set_serialized_particle_data(xyzvxvyvz=q)

def summary(sim,b,m=None):
    """Lifecycle diagnostics from current masses; resets the SFR window."""
    n=sim.N
    if m is None:
        m=np.empty(n);sim.serialize_particle_data(m=m)
    t=b['type'];mask=b.get('disk_mask')
    if mask is None:
        mask=np.zeros(n,dtype=bool);mask[:int(b['disk_count'])]=True
    else:mask=np.asarray(mask,dtype=bool)
    counts={TYPE_NAMES[i]:int(np.sum(t==i)) for i in range(9)}
    alive=(t>=PROTO)&(t<=GIANT)
    out=dict(gas_mass=float(np.sum(m[t==GAS])),stellar_mass=float(np.sum(m[alive])),remnant_mass=float(np.sum(m[(t>=WD)&(t<=BH)])),counts=counts,
      sfr=float(b['born_mass']/b['born_window_myr']) if b['born_window_myr']>0 else 0.,mean_stellar_age=float(np.mean(b['age'][alive])) if np.any(alive) else 0.,
      supernovae_cumulative=int(b['supernovae']),deaths_cumulative=int(b['deaths']),births_cumulative=int(b['births']),mass_return_failed=float(b['failed_return']),baryon_mass=float(np.sum(m[mask])))
    if b.get('ssp'):
        out.update(ssp=True,supernovae_cumulative=int(round(b['sn_total'])),returned_mass=float(b['returned']),return_pending=float(np.sum(b['pending'])),
            feedback_momentum=float(b['p_delivered']),feedback_momentum_unused=float(b['p_unused']))
    b['born_mass']=0.;b['born_window_myr']=0.
    return out
