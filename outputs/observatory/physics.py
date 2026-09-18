# AGENT MAP: model generators return (REBOUND Simulation, metadata, baryons-or-None).
# Keep units, model_revision and diagnostics aligned. Never silently alter saved runs.
# Every structural constant is a parameter with a default that reproduces model revision 2.
# Isolated n_galaxies=1 still bit-matches revision 3; revision 5 is the generator stamp (ISM is baryon-only).
"""CPU models for the local observatory. No remote services are used."""
import os
os.environ.setdefault('OMP_NUM_THREADS','8')
os.environ.setdefault('OMP_WAIT_POLICY','PASSIVE')
import ctypes,math
import numpy as np
import rebound
from scipy.special import iv,kv
from scipy.integrate import cumulative_trapezoid
import stellar
from stellar import MYR_PER_TIME,V_KMS

MODEL_REVISION=5
MIN_PARTICLES_PER_GALAXY=256
CLONE_AZIMUTH={2:0.,3:120.,4:240.,5:180.}

PLANETS=[
# name, mass/Sun (rounded), a, e, I, L, longitude of perihelion, ascending node
('Mercury',1.6601e-7,.38709927,.20563593,7.00497902,252.25032350,77.45779628,48.33076593),
('Venus',2.4478e-6,.72333566,.00677672,3.39467605,181.97909950,131.60246718,76.67984255),
('Earth–Moon',3.0404e-6,1.00000261,.01671123,-.00001531,100.46457166,102.93768193,0),
('Mars',3.2272e-7,1.52371034,.09339410,1.84969142,-4.55343205,-23.94362959,49.55953891),
('Jupiter',9.5479e-4,5.202887,.04838624,1.30439695,34.39644051,14.72847983,100.47390909),
('Saturn',2.8588e-4,9.53667594,.05386179,2.48599187,49.95424423,92.59887831,113.66242448),
('Uranus',4.3662e-5,19.18916464,.04725744,.77263783,313.23810451,170.95427630,74.01692503),
('Neptune',5.1514e-5,30.06992276,.00859048,1.77004347,-55.12002969,44.96476227,131.78422574)]
PLANET_COLORS=['#b7a798','#e5c795','#76c6e7','#d98462','#d2b196','#e0cf9e','#9bd5ce','#6e91df']

def _encounter_defaults():
    d=dict(n_galaxies=1)
    for i in range(2,6):
        d[f'g{i}_mass_ratio']=1.;d[f'g{i}_size_ratio']=1.;d[f'g{i}_sep']=20.;d[f'g{i}_impact']=4.;d[f'g{i}_vrel']=2.
        d[f'g{i}_azimuth']=CLONE_AZIMUTH[i];d[f'g{i}_inclination']=0.;d[f'g{i}_disk_tilt']=0.;d[f'g{i}_spin']=1
    return d

# Defaults reproduce model revision 2 when lifecycle_enabled is False and n_galaxies is 1.
GALAXY_DEFAULTS=dict(n=100000,seed=731,theta=.4,dt=.02,softening=.06,
    disk_mass=1.,halo_mass=20.,disk_fraction=.3,disk_scale=1.2,disk_thickness=.08,halo_scale=4.,warmth=1.,smbh_mass=0.,
    lifecycle_enabled=True,gas_fraction=.2,t_sf=2.,lifecycle_speed=1.,sf_density_bias=.7,imf_mmin=.08,imf_mmax=100.,grow_rate=.2,sn_kick_kms=0.,
    ism_enabled=True,metallicity=1.,cooling_speed=1.,sn_feedback=.15,ram_pressure=1.,n_sf=.1,
    **_encounter_defaults())
PLANET_DEFAULTS=dict(jupiter_mass=1.,planet_mass_scale=[1.]*8,perturber_mass=0.,perturber_a=2.5)

def set_threads(n):
    try:
        omp=ctypes.CDLL('/opt/homebrew/opt/libomp/lib/libomp.dylib')
        omp.omp_set_num_threads(int(n));omp.omp_set_dynamic(0)
    except OSError:pass

TREE_ROOT_DEFAULT=1024.0

def _add_particles(s,pos,vel,mass):
    """Load N particles via one serialized write. Tree gravity is enabled after COM."""
    n=len(mass)
    q=np.empty((n,6),np.float64);q[:,:3]=pos;q[:,3:]=vel
    m=np.ascontiguousarray(mass,np.float64)
    ghost=rebound.Particle()
    for _ in range(n):s.add(ghost)
    s.set_serialized_particle_data(xyzvxvyvz=np.ascontiguousarray(q),m=m)

def apply_tree_box(s,margin=4.0):
    """Grow the Barnes–Hut root so particles stay inside. Never shrinks.
    Isolated revision-4 ICs keep root 1024 (halo truncated at 100); encounters and
    long runs expand when the occupied half-width times margin exceeds the box."""
    if s.N<=0:return float(s.root_size or TREE_ROOT_DEFAULT)
    q,_=arrays(s)
    extent=float(np.max(np.abs(q[:,:3])))
    size=float(s.root_size or TREE_ROOT_DEFAULT)
    half=.5*size
    if extent*margin<=half:return size
    s.root_size=max(TREE_ROOT_DEFAULT,2.0*extent*margin)
    return float(s.root_size)

def arrays(s):
    q=np.empty((s.N,6),dtype=np.float64);m=np.empty(s.N)
    s.serialize_particle_data(xyzvxvyvz=q,m=m)
    return q,m

def directions(rng,n):
    v=rng.normal(size=(n,3));return v/np.linalg.norm(v,axis=1)[:,None]

def galaxy_params(overrides=None):
    P=dict(GALAXY_DEFAULTS)
    for k,v in (overrides or {}).items():
        if k in P and v is not None:P[k]=v
    P['lifecycle_enabled']=bool(P['lifecycle_enabled']);P['ism_enabled']=bool(P.get('ism_enabled',True));P['n']=int(P['n']);P['seed']=int(P['seed'])
    P['n_galaxies']=int(P.get('n_galaxies') or 1)
    if not 1<=P['n_galaxies']<=5:raise ValueError('n_galaxies must be between 1 and 5')
    for i in range(2,6):P[f'g{i}_spin']=int(P[f'g{i}_spin'])
    return P

def split_particle_counts(n,weights):
    """Mass-weighted N split. n_i = max(256, round(n w_i / sum w)); remainder on galaxy A so sum = n."""
    w=np.asarray(weights,dtype=np.float64)
    if w.ndim!=1 or len(w)<1:raise ValueError('weights must be a 1-D array')
    G=len(w);n=int(n)
    if n<MIN_PARTICLES_PER_GALAXY*G:
        raise ValueError('Need at least 256 particles per galaxy (raise N or lower galaxy count).')
    total=float(w.sum())
    if not np.isfinite(total) or total<=0:raise ValueError('Galaxy masses must be positive')
    counts=np.maximum(MIN_PARTICLES_PER_GALAXY,np.round(n*w/total).astype(int))
    counts[0]+=n-int(counts.sum())
    return counts.astype(int)

def _rx(deg):
    t=np.radians(deg);c,s=np.cos(t),np.sin(t)
    return np.array([[1.,0.,0.],[0.,c,-s],[0.,s,c]])

def _ry(deg):
    t=np.radians(deg);c,s=np.cos(t),np.sin(t)
    return np.array([[c,0.,s],[0.,1.,0.],[-s,0.,c]])

def _rz(deg):
    t=np.radians(deg);c,s=np.cos(t),np.sin(t)
    return np.array([[c,-s,0.],[s,c,0.],[0.,0.,1.]])

def _apply_spin(pos,vel,spin):
    """Flip in-plane azimuthal velocity about the clone z-axis. Does not flip v_z."""
    spin=float(spin)
    if spin==1.:return
    xy=np.hypot(pos[:,0],pos[:,1]);ok=xy>1e-12
    x,y=pos[ok,0],pos[ok,1];vx,vy=vel[ok,0],vel[ok,1];r=xy[ok]
    vr=(x*vx+y*vy)/r;vphi=(-y*vx+x*vy)/r*spin
    vel[ok,0]=vr*x/r-vphi*y/r;vel[ok,1]=vr*y/r+vphi*x/r

def build_one_galaxy(rng,n,P):
    """Exponential disk + live Plummer halo (+ optional SMBH replacing one halo particle). No Simulation, no COM shift."""
    n=int(n);Md=float(P['disk_mass']);Mh=float(P['halo_mass']);Rd=float(P['disk_scale']);zd=float(P['disk_thickness']);a=float(P['halo_scale'])
    warm=float(P['warmth']);Mbh=float(P['smbh_mass']);eps=float(P['softening'])
    nd=int(n*float(P['disk_fraction']));nbh=1 if Mbh>0 else 0;nh=n-nd-nbh
    if nh<0:raise ValueError('Galaxy particle budget cannot fit the requested disk fraction and black hole')
    if nh:
        rmax=100.;u=rng.uniform(1e-9,rmax**3/(rmax**2+a*a)**1.5,nh)
        r=a/np.sqrt(u**(-2/3)-1);hp=directions(rng,nh)*r[:,None]
        q=np.empty(nh);done=0
        while done<nh:
            candidate=rng.random((nh-done)*3+16);y=rng.random(len(candidate))*.1
            good=candidate[y<candidate**2*(1-candidate**2)**3.5]
            k=min(len(good),nh-done);q[done:done+k]=good[:k];done+=k
        hv=directions(rng,nh)*(q*np.sqrt(2*Mh/np.sqrt(r*r+a*a)))[:,None]
        grid=np.geomspace(1e-5,1e5,10000);rho=(1+(grid/a)**2)**-2.5
        enclosed=Md*(1-(1+grid/Rd)*np.exp(-grid/Rd))+Mbh
        integrand=rho*enclosed/grid**2
        integral=-cumulative_trapezoid(integrand[::-1],grid[::-1],initial=0)[::-1]
        extra=np.interp(r,grid,integral/rho)
        sigma_h=Mh/(6*np.sqrt(r*r+a*a))
        hv*=np.sqrt(1+extra/sigma_h)[:,None]
    else:
        hp=np.zeros((0,3));hv=np.zeros((0,3));r=np.zeros(0)
    rdisk_max=max(10.,7*Rd)
    R=rng.gamma(2,Rd,nd) if nd else np.zeros(0)
    while nd and np.any(R>rdisk_max):
        mask=R>rdisk_max;R[mask]=rng.gamma(2,Rd,np.sum(mask))
    phi=rng.uniform(0,2*np.pi,nd) if nd else np.zeros(0);z=rng.normal(0,zd,nd) if nd else np.zeros(0)
    dp=np.column_stack((R*np.cos(phi),R*np.sin(phi),z)) if nd else np.zeros((0,3))
    def vc2(rad):
        y=np.maximum(rad/(2*Rd),1e-5)
        return Mh*rad*rad/(rad*rad+a*a)**1.5+2*Md/Rd*y*y*(iv(0,y)*kv(0,y)-iv(1,y)*kv(1,y))+Mbh*rad*rad/(rad*rad+eps*eps)**1.5
    def surface_density(rad):return Md*np.exp(-rad/Rd)/(2*np.pi*Rd**2)
    smax=.35*max(1.,warm)
    def sigma_r(rad):
        vv=vc2(rad);dd=(vc2(rad*1.001)-vc2(rad*.999))/(rad*.002)
        kk=np.maximum(dd/rad+2*vv/rad**2,1e-8)
        return np.clip(warm*1.5*3.36*surface_density(rad)/np.sqrt(kk),.015,smax)
    if nd:
        rr=np.maximum(R,.001);v2=vc2(rr);omega2=v2/rr**2
        derivative=(vc2(rr*1.001)-vc2(rr*.999))/(rr*.002)
        kappa2=np.maximum(derivative/rr+2*omega2,1e-8)
        surface=surface_density(rr)
        sigmaR=sigma_r(rr)
        sigmaPhi=sigmaR*np.sqrt(kappa2/(4*omega2))
        dlog=-rr/Rd+(sigma_r(rr*1.001)**2-sigma_r(rr*.999)**2)/(.002*sigmaR**2)
        vmean=np.sqrt(np.maximum(v2+sigmaR**2*(1-sigmaPhi**2/sigmaR**2+dlog),.05*v2))
        vr=rng.normal(size=nd)*sigmaR;vp=vmean+rng.normal(size=nd)*sigmaPhi
        vertical_frequency=np.sqrt(Mh/(rr*rr+a*a)**1.5+Mbh/(rr*rr+eps*eps)**1.5+4*np.pi*surface/(np.sqrt(2*np.pi)*zd))
        vz=rng.normal(size=nd)*zd*vertical_frequency
        dv=np.column_stack((vr*np.cos(phi)-vp*np.sin(phi),vr*np.sin(phi)+vp*np.cos(phi),vz))
    else:
        dv=np.zeros((0,3))
    pos=np.vstack((dp,hp));vel=np.vstack((dv,hv));mass=np.r_[np.full(nd,Md/nd) if nd else np.zeros(0),np.full(nh,Mh/nh) if nh else np.zeros(0)]
    if nbh:
        pos=np.vstack((pos,np.zeros((1,3))));vel=np.vstack((vel,np.zeros((1,3))));mass=np.r_[mass,Mbh]
    return dict(pos=pos,vel=vel,mass=mass,disk_count=nd,halo_count=nh,smbh_count=nbh)

def place_galaxy(block,sep,impact,vrel,azimuth,inclination,disk_tilt,spin):
    """Spin, tilt about x, then sky placement R=Rz(azimuth)@Ry(inclination) with bulk approach (-vrel,0,0)."""
    pos=np.array(block['pos'],dtype=np.float64,copy=True);vel=np.array(block['vel'],dtype=np.float64,copy=True)
    _apply_spin(pos,vel,spin)
    if disk_tilt:
        Rx=_rx(disk_tilt);pos=pos@Rx.T;vel=vel@Rx.T
    R=_rz(azimuth)@_ry(inclination)
    offset=R@np.array([float(sep),float(impact),0.])
    bulk=R@np.array([-float(vrel),0.,0.])
    pos=pos@R.T+offset;vel=vel@R.T+bulk
    out=dict(block);out['pos']=pos;out['vel']=vel;return out

def _clone_params(P,mass_ratio,size_ratio):
    Q=dict(P)
    Q['disk_mass']=float(P['disk_mass'])*mass_ratio;Q['halo_mass']=float(P['halo_mass'])*mass_ratio;Q['smbh_mass']=float(P['smbh_mass'])*mass_ratio
    Q['disk_scale']=float(P['disk_scale'])*size_ratio;Q['disk_thickness']=float(P['disk_thickness'])*size_ratio;Q['halo_scale']=float(P['halo_scale'])*size_ratio
    return Q

def disk_mask_from_meta(meta,n=None):
    n=int(n if n is not None else meta.get('n',0));mask=np.zeros(n,dtype=bool)
    gals=meta.get('galaxies')
    if gals:
        for g in gals:
            a=int(g['start']);mask[a:a+int(g['disk_count'])]=True
    else:mask[:int(meta.get('disk_count',n))]=True
    return mask

def galaxy(n=100000,seed=731,theta=.4,dt=.02,**overrides):
    """Live Plummer halo + exponential stellar disk with approximate Jeans support; optional central black hole
    and optional stellar lifecycle plus a laboratory two-phase ISM. n_galaxies=1 is the isolated revision-3 lab (bit-identical ICs when lifecycle is off).
    2–5 galaxies share N on one leapfrog tree. Units: G=1, mass=1e10 solar masses, length=3 kpc, time=24.50 Myr.
    No artificial spiral pattern, damping, prescribed orbits, or frozen halo. Returns (sim, meta, baryons|None).
    """
    P=galaxy_params(dict(overrides,n=n,seed=seed,theta=theta,dt=dt))
    n=P['n'];G=P['n_galaxies'];eps=float(P['softening']);theta=float(P['theta']);dt=float(P['dt'])
    Md=float(P['disk_mass']);Mh=float(P['halo_mass']);Mbh=float(P['smbh_mass']);M_A=Md+Mh+Mbh
    weights=[M_A]+[float(P[f'g{i}_mass_ratio'])*M_A for i in range(2,G+1)]
    counts=split_particle_counts(n,weights)
    blocks=[];start=0;galaxies=[]
    rngs=[np.random.default_rng(P['seed']+i) for i in range(G)]
    for i in range(G):
        if i==0:Qi=P;mass_ratio=1.;size_ratio=1.
        else:
            k=i+1;mass_ratio=float(P[f'g{k}_mass_ratio']);size_ratio=float(P[f'g{k}_size_ratio'])
            Qi=_clone_params(P,mass_ratio,size_ratio)
        block=build_one_galaxy(rngs[i],int(counts[i]),Qi)
        if i:
            k=i+1
            block=place_galaxy(block,P[f'g{k}_sep'],P[f'g{k}_impact'],P[f'g{k}_vrel'],P[f'g{k}_azimuth'],P[f'g{k}_inclination'],P[f'g{k}_disk_tilt'],P[f'g{k}_spin'])
        ni=int(counts[i]);nd,nh,nbh=block['disk_count'],block['halo_count'],block['smbh_count']
        galaxies.append(dict(id=i+1,start=start,n=ni,disk_count=nd,halo_count=nh,smbh_count=nbh,mass_ratio=mass_ratio,size_ratio=size_ratio))
        blocks.append(block);start+=ni
    pos=np.vstack([b['pos'] for b in blocks]);vel=np.vstack([b['vel'] for b in blocks]);mass=np.concatenate([b['mass'] for b in blocks])
    disk_mask=np.zeros(n,dtype=np.uint8)
    for g,b in zip(galaxies,blocks):disk_mask[g['start']:g['start']+b['disk_count']]=1
    s=rebound.Simulation();s.G=1;s.dt=dt;s.integrator='leapfrog';s.softening=eps
    s.root_size=2048 if G>1 else TREE_ROOT_DEFAULT;s.N_root_x=s.N_root_y=s.N_root_z=1
    _add_particles(s,pos,vel,mass)
    s.move_to_com()
    apply_tree_box(s)
    s.gravity='tree';s.opening_angle2=theta**2
    q0,m0=arrays(s)
    for g in galaxies:
        sl=slice(g['start'],g['start']+g['n']);mw=m0[sl]
        g['com0']=np.average(q0[sl,:3],axis=0,weights=mw).tolist()
    baryons=stellar.new_baryons(rngs[0],n,disk_mask,P) if P['lifecycle_enabled'] else None
    if baryons is not None:
        for g in galaxies:
            if g['smbh_count']:baryons['type'][g['start']+g['n']-1]=stellar.SMBH
    nd=int(sum(g['disk_count'] for g in galaxies));nh=int(sum(g['halo_count'] for g in galaxies));nbh=int(sum(g['smbh_count'] for g in galaxies))
    if G==1:
        title='Isolated disk + live halo'+(' + central black hole' if nbh else '')
        encounter_text=''
    else:
        title=f'{G}-galaxy encounter'+(' + central black holes' if nbh else '')
        encounter_text=' Galaxies share one live N-body tree; there is no prescribed merger path. Superparticles, not resolved galaxies. Barnes–Hut with several dense concentrations at the same θ is coarser than an isolated galaxy. Birth-galaxy colors stay frozen at t=0. The default 245 Myr span is a first passage, not a remnant, and not MW–M31.'
    if P['lifecycle_enabled'] and P.get('ism_enabled',True):
        lifecycle_text=(' Collisionless bookkeeping still sets who is a star; gas parcels also feel a grid pressure force, ram drag, CIE-like cooling Λ(T,Z), and blastwave-delayed supernova heat. Star formation is allowed only in cold, dense, non-expanding gas. This is not SPH: no Riemann solver, no resolved Jeans mass, no chemistry. Superparticle SN coupling is a laboratory parameter. lifecycle_speed is a stellar clock, not a hydro calibration.')
    elif P['lifecycle_enabled']:
        lifecycle_text=(' Collisionless gas parcels form stars on a density-biased timescale; stars age on a mass-lifetime clock and die into white dwarfs, neutron stars or black holes, returning mass to nearby gas. lifecycle_speed is a laboratory clock, not a calibration. ISM hydro is off: no cooling, ram pressure or blastwave heat.')
    else:
        lifecycle_text=' Stellar lifecycle disabled: equal-mass collisionless disk.'
    isolated_text=' n_galaxies=1 is the isolated revision-3 lab (same distribution function; generator stamped revision 5).' if G==1 else ''
    camera=1.3*max(np.linalg.norm(g['com0']) for g in galaxies) if G>1 else None
    meta=dict(mode='galaxy',model_revision=MODEL_REVISION,n=n,disk_count=nd,halo_count=nh,smbh_count=nbh,n_galaxies=G,galaxies=galaxies,title=title,
      length_unit='kpc',length_scale=3,time_unit='Myr',time_scale=MYR_PER_TIME,mass_unit_solar=1e10,velocity_unit_kms=V_KMS,theta=theta,softening=eps,dt=dt,
      integrator='Leapfrog · tree gravity'+(' · stellar lifecycle' if P['lifecycle_enabled'] else '')+(' · two-phase ISM' if P['lifecycle_enabled'] and P.get('ism_enabled',True) else ''),seed=P['seed'],params=P,lifecycle_enabled=P['lifecycle_enabled'],ism_enabled=bool(P['lifecycle_enabled'] and P.get('ism_enabled',True)),
      frame_layout='xyzsmt',bytes_per_particle=24,
      description='An exponential stellar disk in a live Plummer dark-matter halo. All particles gravitate. Warm disk with approximate Jeans support; not a calibrated equilibrium galaxy.'+lifecycle_text+isolated_text+encounter_text+' Each particle is a superparticle, not a resolved star.',
      sources=['https://rebound.hanno-rein.de/c_examples/selfgravity_plummer/','https://galaxiesbook.org/chapters/II-01.-Gravitation-in-Galactic-Disks_3-Gravitational-potentials-from-disk-density-distributions.html','https://ui.adsabs.harvard.edu/abs/2001MNRAS.322..231K','https://ui.adsabs.harvard.edu/abs/1965ApJ...142..531F','https://ui.adsabs.harvard.edu/abs/1972ApJ...176....1G','https://ui.adsabs.harvard.edu/abs/1993ApJ...414..522S','https://ui.adsabs.harvard.edu/abs/2006ApJ...653..960S'])
    if camera is not None:meta['camera_distance']=float(camera)
    return s,meta,baryons

def planets(jupiter_mass=1,planet_mass_scale=None,perturber_mass=0.,perturber_a=2.5,**_):
    scales=list(planet_mass_scale) if planet_mass_scale else [1.]*8
    scales=[float(x) for x in (scales+[1.]*8)[:8]]
    s=rebound.Simulation();s.G=4*math.pi**2;s.integrator='ias15';s.add(m=1)
    bodies=[dict(name='Sun',mass=1,a=0,color='#ffd092')]
    for (name,m,a,e,inc,L,peri,node),scale,color in zip(PLANETS,scales,PLANET_COLORS):
        m=m*scale*(jupiter_mass if name=='Jupiter' else 1)
        s.add(primary=s.particles[0],m=m,a=a,e=e,inc=math.radians(inc),Omega=math.radians(node),omega=math.radians(peri-node),M=math.radians(L-peri))
        bodies.append(dict(name=name,mass=m,a=a,e=e,inc=inc,L=L,peri=peri,node=node,color=color,scale=scale))
    if perturber_mass and perturber_mass>0:
        pa=float(perturber_a)
        s.add(primary=s.particles[0],m=float(perturber_mass),a=pa,e=.05,inc=math.radians(2.),Omega=0.,omega=0.,M=math.radians(90.))
        bodies.append(dict(name='Perturber',mass=float(perturber_mass),a=pa,e=.05,inc=2.,L=90.,peri=0.,node=0.,color='#e08fd0',scale=1.))
    s.move_to_com()
    title='Solar System'
    if jupiter_mass!=1:title+=f' · Jupiter {jupiter_mass:g}×'
    if any(abs(x-1)>1e-9 for x in scales):title+=' · scaled planets'
    if perturber_mass and perturber_mass>0:title+=' · perturber'
    return s,dict(mode='planets',model_revision=MODEL_REVISION,n=s.N,title=title,bodies=bodies,length_unit='AU',length_scale=1,time_unit='yr',time_scale=1,
      integrator='IAS15 · direct gravity',jupiter_mass=jupiter_mass,planet_mass_scale=scales,perturber_mass=float(perturber_mass or 0),perturber_a=float(perturber_a),
      frame_layout='xyzsmt',bytes_per_particle=24,lifecycle_enabled=False,
      description='Newtonian Sun + planetary bodies, initialized from JPL approximate J2000 elements and rounded mass ratios. Earth includes the Moon. Not a current ephemeris. Planet sizes are enlarged for visibility; orbital distances are linear.',
      sources=['https://ssd.jpl.nasa.gov/planets/approx_pos.html','https://ssd.jpl.nasa.gov/planets/phys_par.html']),None

def _galaxy_com(p,m,sl):
    mw=m[sl]
    return np.average(p[sl],axis=0,weights=mw),np.sum(mw)

def diagnostics(s,meta,baryons=None,sample=192):
    q,m=arrays(s);p=q[:,:3];v=q[:,3:];angular=np.sum(m[:,None]*np.cross(p,v),axis=0)
    kinetic=float(.5*np.sum(m[:,None]*v*v))
    if meta['mode']=='planets':
        energy=float(s.energy());sampled=False;energy_sigma=0.
    else:
        sampled=len(m)>4096;potential=0.;variance=0.
        rng=np.random.default_rng(29)
        mask=disk_mask_from_meta(meta,s.N)
        groups=[np.flatnonzero(mask),np.flatnonzero(~mask)]
        groups=[g for g in groups if len(g)]
        for group in groups:
            indices=rng.choice(group,min(sample,len(group)),replace=False) if sampled else group
            total=0.;terms=[]
            for i in indices:
                dist=np.sqrt(np.sum((p-p[i])**2,axis=1)+s.softening**2);dist[i]=np.inf
                term=m[i]*np.sum(m/dist);total+=term;terms.append(term)
            potential-=.5*total*len(group)/len(indices)
            if sampled:variance+=.25*len(group)**2*np.var(terms,ddof=1)/len(indices)*(1-len(indices)/len(group))
        energy=kinetic+potential;energy_sigma=float(np.sqrt(variance))
    scale=float(meta.get('length_scale',3));gals=meta.get('galaxies')
    if not gals and meta.get('mode')=='galaxy':
        nd=int(meta.get('disk_count',s.N));nh=int(meta.get('halo_count',max(0,s.N-nd)))
        gals=[dict(id=1,start=0,n=s.N,disk_count=nd,halo_count=nh,smbh_count=int(meta.get('smbh_count',0)))]
    encounter_gals=[];disk_hrs=[];disk_masses=[];halo_hrs=[];halo_masses=[]
    for g in gals or []:
        a=int(g['start']);ng=int(g['n']);nd=int(g['disk_count']);nh=int(g.get('halo_count',0))
        sl=slice(a,a+ng);com,mass=_galaxy_com(p,m,sl);vcom=np.average(v[sl],axis=0,weights=m[sl])
        disk_p=p[a:a+nd];disk_hr=float(np.median(np.linalg.norm(disk_p-com,axis=1))) if nd else None
        halo_p=p[a+nd:a+nd+nh];halo_hr=float(np.median(np.linalg.norm(halo_p-com,axis=1))) if nh else None
        if disk_hr is not None:disk_hrs.append(disk_hr);disk_masses.append(float(np.sum(m[a:a+nd])))
        if halo_hr is not None:halo_hrs.append(halo_hr);halo_masses.append(float(np.sum(m[a+nd:a+nd+nh])))
        encounter_gals.append(dict(id=int(g.get('id',0)),mass=float(mass),com=com.tolist(),vcom=vcom.tolist(),
            disk_half_radius_kpc=None if disk_hr is None else disk_hr*scale,halo_half_radius_kpc=None if halo_hr is None else halo_hr*scale))
    if disk_hrs:
        w=np.array(disk_masses);disk_half=float(np.average(disk_hrs,weights=w))
    else:
        nd=int(meta.get('disk_count',s.N));disk_half=float(np.median(np.linalg.norm(p[:nd],axis=1)))
    if halo_hrs:
        w=np.array(halo_masses);halo_half=float(np.average(halo_hrs,weights=w))
    else:
        nd=int(meta.get('disk_count',s.N));nh_end=nd+int(meta.get('halo_count',s.N-nd));halo_half=float(np.median(np.linalg.norm(p[nd:nh_end],axis=1))) if nd<nh_end else None
    out=dict(energy=energy,energy_sampled=sampled,energy_sigma=energy_sigma,angular_momentum=angular.tolist(),total_mass=float(np.sum(m)),
      disk_half_radius=disk_half,halo_half_radius=halo_half,finite=bool(np.all(np.isfinite(q))),particles=s.N)
    if encounter_gals:
        enc=dict(galaxies=encounter_gals)
        if len(encounter_gals)>=2:
            c0=np.array(encounter_gals[0]['com']);c1=np.array(encounter_gals[1]['com'])
            v0=np.array(encounter_gals[0]['vcom']);v1=np.array(encounter_gals[1]['vcom'])
            enc['separation_12']=float(np.linalg.norm(c0-c1));enc['vrel_12']=float(np.linalg.norm(v0-v1))
            pair_min=enc['separation_12']
            for i in range(len(encounter_gals)):
                ci=np.array(encounter_gals[i]['com'])
                for j in range(i+1,len(encounter_gals)):
                    pair_min=min(pair_min,float(np.linalg.norm(ci-np.array(encounter_gals[j]['com']))))
            enc['min_separation']=pair_min;enc['min_separation_time']=float(s.t)
        out['encounter']=enc
    if baryons is not None:out['lifecycle']=stellar.summary(s,baryons,m)
    return out
