# AGENT MAP: baryon lifecycle + optional grid ISM. Gas/hot → protostar → MS → giant → WD/NS/BH.
# Gravity always uses the current REBOUND slot masses; this module changes those masses.
# Clock uses m_star (Msun). Force uses slot mass (code units). N never changes.
# ISM (ism.py) is not SPH and not MESA. lifecycle_speed is a laboratory clock, not a calibration.
# Disk occupancy is disk_mask, not a global prefix — required for concatenated [disk|halo|smbh] galaxies.
# peek() is for per-frame T/phase; summary() also resets the SFR window for the 40-frame energy cadence.
"""Stellar birth, growth and death for the observatory galaxy model."""
import numpy as np
import ism

# Galaxy code units: G=1, mass 1e10 Msun, length 3 kpc. Derived time and velocity units.
MYR_PER_TIME=24.50          # one code time unit in Myr
V_KMS=119.7                 # one code velocity unit in km/s
GAS,PROTO,MS,GIANT,WD,NS,BH,HALO,SMBH,HOT=range(10)
TYPE_NAMES=['gas','protostar','main_sequence','giant','white_dwarf','neutron_star','black_hole','halo','smbh','hot_gas']
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
    b=dict(type=types,age=age,m_star=m_star,birth_time=birth,disk_mask=disk_mask.copy(),disk_count=int(np.sum(disk_mask)),debt=0.,born_mass=0.,born_window_myr=0.,supernovae=0,deaths=0,births=0,failed_return=0.)
    ism.attach(b,params)
    return b

def save_baryons(path,b):
    mask=b.get('disk_mask')
    if mask is None:
        mask=np.zeros(len(b['type']),np.uint8);mask[:int(b['disk_count'])]=1
    scalars=np.array([b['disk_count'],b['debt'],b['born_mass'],b['born_window_myr'],b['supernovae'],b['deaths'],b['births'],b['failed_return'],
                      b.get('metals_produced',0.),b.get('sn_heat',0.),b.get('shock_heat',0.),b.get('sn_momentum',0.),b.get('cloud_heat',0.)],dtype=np.float64)
    kw=dict(type=b['type'],age=b['age'],m_star=b['m_star'],birth_time=b['birth_time'],disk_mask=np.asarray(mask,dtype=np.uint8),scalars=scalars)
    for k in ('u','Z','cool_delay','z_birth','x'):
        if k in b:kw[k]=np.asarray(b[k])
    np.savez(path,**kw)

def load_baryons(path):
    z=np.load(path);s=z['scalars'];n=len(z['type']);disk_count=int(s[0])
    if 'disk_mask' in z.files:mask=z['disk_mask'].astype(np.uint8)
    else:
        mask=np.zeros(n,np.uint8);mask[:disk_count]=1
    b=dict(type=z['type'].astype(np.uint8),age=z['age'],m_star=z['m_star'],birth_time=z['birth_time'],disk_mask=mask,disk_count=disk_count,debt=float(s[1]),born_mass=float(s[2]),born_window_myr=float(s[3]),supernovae=int(s[4]),deaths=int(s[5]),births=int(s[6]),failed_return=float(s[7]),
           metals_produced=float(s[8]) if len(s)>8 else 0.,sn_heat=float(s[9]) if len(s)>9 else 0.,shock_heat=float(s[10]) if len(s)>10 else 0.,
           sn_momentum=float(s[11]) if len(s)>11 else 0.,cloud_heat=float(s[12]) if len(s)>12 else 0.)
    for k in ('u','Z','cool_delay','z_birth','x'):
        if k in z.files:b[k]=z[k].astype(np.float64)
    ism.attach(b,{})
    return b

def _cells(pos):
    """Integer cell key per row; keys are sortable int64 from a shifted 3D grid."""
    ijk=np.floor(pos/CELL).astype(np.int64)+(1<<20)
    return (ijk[:,0]<<42)|(ijk[:,1]<<21)|ijk[:,2]

def _neighbour_idx(key,keys_sorted,order):
    """Indices (into the keyed arrays) of members in the same cell, else the 26 surrounding cells."""
    def lookup(k):
        lo=np.searchsorted(keys_sorted,k,'left');hi=np.searchsorted(keys_sorted,k,'right');return order[lo:hi]
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
    """Advance the lifecycle by one gravity step. Mutates REBOUND masses and (for kicks/ISM) velocities in place."""
    speed=float(params['lifecycle_speed']);dt_myr=dt_model*MYR_PER_TIME*speed
    types=b['type'];age=b['age'];m_star=b['m_star']
    rng=np.random.default_rng([int(seed)&0xffffffff,int(sim.steps_done)&0xffffffff])
    n=sim.N;q=np.empty((n,6));m=np.empty(n);sim.serialize_particle_data(xyzvxvyvz=q,m=m)
    pos=q[:,:3];dm=np.zeros(n);metal_add=np.zeros(n);dv=False;changed=False
    ism.attach(b,params)
    gas_all=np.flatnonzero(ism.is_gas(types));cold=np.flatnonzero(types==GAS)
    gas_keys=None;gas_order=None;cold_keys=None;cold_order=None
    if len(gas_all):
        keys=_cells(pos[gas_all]);gas_order=np.argsort(keys,kind='stable');gas_keys=keys[gas_order]
    if len(cold):
        ckeys=_cells(pos[cold]);cold_order=np.argsort(ckeys,kind='stable');cold_keys=ckeys[cold_order]
    # ---- aging ----
    alive=(types>=PROTO)&(types<=GIANT)
    age[alive]+=dt_myr
    tms=lifetime_myr(np.where(alive,m_star,1.))
    # protostar -> MS; accrete only from cold gas
    grow=np.flatnonzero(types==PROTO)
    if len(grow) and len(cold) and float(params['grow_rate'])>0:
        rate=float(params['grow_rate'])*dt_myr
        pkeys=_cells(pos[grow])
        for gi,key in zip(grow,pkeys):
            nb=_neighbour_idx(key,cold_keys,cold_order)
            if not len(nb):continue
            src=cold[nb];avail=m[src]+dm[src];want=min(float(avail.sum())*.5,m[gi]*rate)
            if want<=0:continue
            take=avail/avail.sum()*want;dm[src]-=take;dm[gi]+=want;changed=True
    done=grow[age[grow]>=prems_myr(m_star[grow])] if len(grow) else grow
    types[done]=MS
    # MS -> giant
    ms_idx=np.flatnonzero(types==MS);to_giant=ms_idx[age[ms_idx]>=.9*tms[ms_idx]];types[to_giant]=GIANT
    # giant -> remnant
    giants=np.flatnonzero(types==GIANT);dying=giants[age[giants]>=tms[giants]]
    kick_kms=float(params['sn_kick_kms']);ism_on=bool(params.get('ism_enabled',False))
    if len(dying):
        rtype,rmass=remnant_of(m_star[dying]);frac=np.clip(rmass/np.maximum(m_star[dying],1e-6),0,1)
        slot=m[dying]+dm[dying];ejecta=slot*(1-frac)
        dkeys=_cells(pos[dying]) if len(gas_all) else None
        kicks=[]
        for j,(di,e) in enumerate(zip(dying,ejecta)):
            if e>0:
                nb=_neighbour_idx(dkeys[j],gas_keys,gas_order) if len(gas_all) else np.empty(0,np.int64)
                if len(nb):
                    src=gas_all[nb];dm[src]+=e/len(src);dm[di]-=e
                    y=ism.YIELD_SN if m_star[di]>=8 else ism.YIELD_AGB
                    metal_add[src]+=y*e/len(src);b['metals_produced']=float(b.get('metals_produced',0)+y*e)
                    if ism_on and m_star[di]>=8:
                        if ism.deposit_feedback(b,m+dm,q[:,3:],pos,src,pos[di],int(di),e,params):dv=True
                else:b['failed_return']+=float(e)
            if rtype[j] in (NS,BH) and kick_kms>0:kicks.append(di)
        types[dying]=rtype;b['deaths']+=len(dying);b['supernovae']+=int(np.sum(m_star[dying]>=8));changed=True
        if kicks:
            kicks=np.array(kicks);dirs=rng.normal(size=(len(kicks),3));dirs/=np.linalg.norm(dirs,axis=1)[:,None]
            q[kicks,3:]+=dirs*(kick_kms/V_KMS);dv=True
    # mix metals into gas before masses are written
    if np.any(metal_add) or np.any(dm):
        gas=ism.is_gas(types)
        m_old=m+0.
        # Z is metal mass fraction of the current slot mass
        if np.any(gas):
            metal=b['Z']*m_old;metal+=metal_add
            m_new=np.maximum(m_old+dm,0.)
            nz=gas&(m_new>1e-18)
            b['Z'][nz]=metal[nz]/m_new[nz]
    # ---- birth ----
    t_sf_myr=max(float(params['t_sf'])*1000.,1.)
    m_eff=m+dm
    if ism_on:
        eligible=np.flatnonzero(ism.star_forming(pos,q[:,3:],m_eff,b['u'],types,params,b.get('x')))
    else:
        eligible=np.flatnonzero(types==GAS)
    pool_mass=float(np.sum(m_eff[eligible])) if len(eligible) else 0.
    if pool_mass>0:
        b['debt']+=pool_mass/t_sf_myr*dt_myr
        slot_mass=pool_mass/len(eligible);k=int(min(b['debt']//slot_mass,len(eligible)))
        if k>0:
            ekeys=_cells(pos[eligible]);eord=np.argsort(ekeys,kind='stable');ek=ekeys[eord]
            cell_index=np.searchsorted(ek,ekeys);counts=np.bincount(cell_index,minlength=len(ek)+1);density=counts[cell_index].astype(np.float64)
            rank=np.argsort(np.argsort(density))/max(len(density)-1,1)
            bias=float(params['sf_density_bias']);score=bias*rank+(1-bias)*rng.random(len(density))
            pick=eligible[np.argpartition(-score,k-1)[:k]] if k<len(eligible) else eligible
            born_mass=float(np.sum(m_eff[pick]));b['debt']-=born_mass;b['born_mass']+=born_mass;b['births']+=len(pick)
            ms=kroupa_masses(rng,len(pick),params['imf_mmin'],params['imf_mmax'])
            m_star[pick]=ms;age[pick]=0.;b['birth_time'][pick]=sim.t
            if 'z_birth' in b:b['z_birth'][pick]=b['Z'][pick]
            types[pick]=np.where(ms>=2.,PROTO,MS)
    b['born_window_myr']+=dt_myr
    # ---- ISM hydro / cooling / ram (after mass return, before writeback) ----
    if ism_on:
        if ism.step(q,m_eff,b,params,dt_model):dv=True
    # ---- write back ----
    if changed and np.any(dm):
        m=np.maximum(m+dm,0.)
        sim.set_serialized_particle_data(m=m)
    if dv:sim.set_serialized_particle_data(xyzvxvyvz=q)

def peek(sim,b,m=None):
    """Lifecycle diagnostics from current masses. Does not reset the SFR window."""
    n=sim.N
    if m is None:
        m=np.empty(n);sim.serialize_particle_data(m=m)
    t=b['type'];mask=b.get('disk_mask')
    if mask is None:
        mask=np.zeros(n,dtype=bool);mask[:int(b['disk_count'])]=True
    else:mask=np.asarray(mask,dtype=bool)
    counts={TYPE_NAMES[i]:int(np.sum(t==i)) for i in range(len(TYPE_NAMES))}
    alive=(t>=PROTO)&(t<=GIANT)
    gas_mass=float(np.sum(m[ism.is_gas(t)]))
    out=dict(gas_mass=gas_mass,stellar_mass=float(np.sum(m[alive])),remnant_mass=float(np.sum(m[(t>=WD)&(t<=BH)])),counts=counts,
      sfr=float(b['born_mass']/b['born_window_myr']) if b['born_window_myr']>0 else 0.,mean_stellar_age=float(np.mean(b['age'][alive])) if np.any(alive) else 0.,
      supernovae_cumulative=int(b['supernovae']),deaths_cumulative=int(b['deaths']),births_cumulative=int(b['births']),mass_return_failed=float(b['failed_return']),baryon_mass=float(np.sum(m[mask])))
    if 'z_birth' in b and np.any(alive):
        out['mean_stellar_metallicity']=float(np.average(b['z_birth'][alive]/ism.Z_SOLAR,weights=np.maximum(m[alive],1e-30)))
    out.update(ism.summary_fields(b,m))
    return out

def summary(sim,b,m=None):
    """Lifecycle diagnostics; resets the SFR window used by the expensive energy cadence."""
    out=peek(sim,b,m)
    b['born_mass']=0.;b['born_window_myr']=0.
    return out
