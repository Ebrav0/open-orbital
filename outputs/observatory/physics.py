# AGENT MAP: model generators return (REBOUND Simulation, metadata, baryons-or-None).
# Keep units, model_revision and diagnostics aligned. Never silently alter saved runs.
# Every structural constant is a parameter with a default that reproduces model revision 2.
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

MODEL_REVISION=3

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

# Defaults reproduce model revision 2 when lifecycle_enabled is False.
GALAXY_DEFAULTS=dict(n=100000,seed=731,theta=.4,dt=.02,softening=.06,
    disk_mass=1.,halo_mass=20.,disk_fraction=.3,disk_scale=1.2,disk_thickness=.08,halo_scale=4.,warmth=1.,smbh_mass=0.,
    lifecycle_enabled=True,gas_fraction=.2,t_sf=2.,lifecycle_speed=1.,sf_density_bias=.7,imf_mmin=.08,imf_mmax=100.,grow_rate=.2,sn_kick_kms=0.)
PLANET_DEFAULTS=dict(jupiter_mass=1.,planet_mass_scale=[1.]*8,perturber_mass=0.,perturber_a=2.5)

def set_threads(n):
    try:
        omp=ctypes.CDLL('/opt/homebrew/opt/libomp/lib/libomp.dylib')
        omp.omp_set_num_threads(int(n));omp.omp_set_dynamic(0)
    except OSError:pass

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
    P['lifecycle_enabled']=bool(P['lifecycle_enabled']);P['n']=int(P['n']);P['seed']=int(P['seed'])
    return P

def galaxy(n=100000,seed=731,theta=.4,dt=.02,**overrides):
    """Live Plummer halo + exponential stellar disk with approximate Jeans support; optional central black hole
    and optional collisionless stellar lifecycle. Units: G=1, mass=1e10 solar masses, length=3 kpc, time=24.50 Myr.
    No artificial spiral pattern, damping, prescribed orbits, or frozen halo. Returns (sim, meta, baryons|None).
    """
    P=galaxy_params(dict(overrides,n=n,seed=seed,theta=theta,dt=dt))
    n=P['n'];rng=np.random.default_rng(P['seed'])
    Md=float(P['disk_mass']);Mh=float(P['halo_mass']);Rd=float(P['disk_scale']);zd=float(P['disk_thickness']);a=float(P['halo_scale'])
    warm=float(P['warmth']);Mbh=float(P['smbh_mass']);eps=float(P['softening']);theta=float(P['theta']);dt=float(P['dt'])
    nd=int(n*float(P['disk_fraction']));nbh=1 if Mbh>0 else 0;nh=n-nd-nbh
    # Halo: Plummer sphere, truncated only in the extreme tail at 100 code lengths (~300 kpc).
    rmax=100.;u=rng.uniform(1e-9,rmax**3/(rmax**2+a*a)**1.5,nh)
    r=a/np.sqrt(u**(-2/3)-1);hp=directions(rng,nh)*r[:,None]
    # Plummer distribution function: p(q) proportional q^2 (1-q^2)^(7/2).
    q=np.empty(nh);done=0
    while done<nh:
        candidate=rng.random((nh-done)*3+16);y=rng.random(len(candidate))*.1
        good=candidate[y<candidate**2*(1-candidate**2)**3.5]
        k=min(len(good),nh-done);q[done:done+k]=good[:k];done+=k
    hv=directions(rng,nh)*(q*np.sqrt(2*Mh/np.sqrt(r*r+a*a)))[:,None]
    # Match spherical Jeans second moments with the disk monopole and central mass included.
    grid=np.geomspace(1e-5,1e5,10000);rho=(1+(grid/a)**2)**-2.5
    enclosed=Md*(1-(1+grid/Rd)*np.exp(-grid/Rd))+Mbh
    integrand=rho*enclosed/grid**2
    integral=-cumulative_trapezoid(integrand[::-1],grid[::-1],initial=0)[::-1]
    extra=np.interp(r,grid,integral/rho)
    sigma_h=Mh/(6*np.sqrt(r*r+a*a))
    hv*=np.sqrt(1+extra/sigma_h)[:,None]
    # Disk: exponential surface density, gaussian vertical profile.
    rdisk_max=max(10.,7*Rd)
    R=rng.gamma(2,Rd,nd)
    while np.any(R>rdisk_max):
        mask=R>rdisk_max;R[mask]=rng.gamma(2,Rd,np.sum(mask))
    phi=rng.uniform(0,2*np.pi,nd);z=rng.normal(0,zd,nd)
    dp=np.column_stack((R*np.cos(phi),R*np.sin(phi),z))
    # Freeman exponential-disk rotation curve, plus spherical Plummer halo, plus softened central mass.
    def vc2(rad):
        y=np.maximum(rad/(2*Rd),1e-5)
        return Mh*rad*rad/(rad*rad+a*a)**1.5+2*Md/Rd*y*y*(iv(0,y)*kv(0,y)-iv(1,y)*kv(1,y))+Mbh*rad*rad/(rad*rad+eps*eps)**1.5
    def surface_density(rad):return Md*np.exp(-rad/Rd)/(2*np.pi*Rd**2)
    smax=.35*max(1.,warm)
    def sigma_r(rad):
        vv=vc2(rad);dd=(vc2(rad*1.001)-vc2(rad*.999))/(rad*.002)
        kk=np.maximum(dd/rad+2*vv/rad**2,1e-8)
        return np.clip(warm*1.5*3.36*surface_density(rad)/np.sqrt(kk),.015,smax)
    rr=np.maximum(R,.001);v2=vc2(rr);omega2=v2/rr**2
    derivative=(vc2(rr*1.001)-vc2(rr*.999))/(rr*.002)
    kappa2=np.maximum(derivative/rr+2*omega2,1e-8)
    surface=surface_density(rr)
    sigmaR=sigma_r(rr)
    sigmaPhi=sigmaR*np.sqrt(kappa2/(4*omega2))
    # Radial Jeans asymmetric drift, using the actual dispersion gradient.
    dlog=-rr/Rd+(sigma_r(rr*1.001)**2-sigma_r(rr*.999)**2)/(.002*sigmaR**2)
    vmean=np.sqrt(np.maximum(v2+sigmaR**2*(1-sigmaPhi**2/sigmaR**2+dlog),.05*v2))
    vr=rng.normal(size=nd)*sigmaR;vp=vmean+rng.normal(size=nd)*sigmaPhi
    vertical_frequency=np.sqrt(Mh/(rr*rr+a*a)**1.5+Mbh/(rr*rr+eps*eps)**1.5+4*np.pi*surface/(np.sqrt(2*np.pi)*zd))
    vz=rng.normal(size=nd)*zd*vertical_frequency
    dv=np.column_stack((vr*np.cos(phi)-vp*np.sin(phi),vr*np.sin(phi)+vp*np.cos(phi),vz))
    pos=np.vstack((dp,hp));vel=np.vstack((dv,hv));mass=np.r_[np.full(nd,Md/nd),np.full(nh,Mh/nh)]
    if nbh:
        pos=np.vstack((pos,np.zeros((1,3))));vel=np.vstack((vel,np.zeros((1,3))));mass=np.r_[mass,Mbh]
    s=rebound.Simulation();s.G=1;s.dt=dt;s.integrator='leapfrog';s.softening=eps
    s.root_size=1024;s.N_root_x=s.N_root_y=s.N_root_z=1;s.gravity='tree';s.opening_angle2=theta**2
    for p,v,m in zip(pos,vel,mass):s.add(m=m,x=p[0],y=p[1],z=p[2],vx=v[0],vy=v[1],vz=v[2])
    s.move_to_com()
    baryons=stellar.new_baryons(rng,n,nd,P) if P['lifecycle_enabled'] else None
    if baryons is not None and nbh:baryons['type'][-1]=stellar.SMBH
    lifecycle_text=(' Collisionless gas parcels form stars on a density-biased timescale; stars age on a mass-lifetime clock and die into white dwarfs, neutron stars or black holes, returning mass to nearby gas. lifecycle_speed is a laboratory clock, not a calibration. No hydrodynamics, cooling, binaries or chemistry.'
        if P['lifecycle_enabled'] else ' Stellar lifecycle disabled: equal-mass collisionless disk.')
    meta=dict(mode='galaxy',model_revision=MODEL_REVISION,n=n,disk_count=nd,halo_count=nh,smbh_count=nbh,title='Isolated disk + live halo'+(' + central black hole' if nbh else ''),
      length_unit='kpc',length_scale=3,time_unit='Myr',time_scale=MYR_PER_TIME,mass_unit_solar=1e10,velocity_unit_kms=V_KMS,theta=theta,softening=eps,dt=dt,
      integrator='Leapfrog · tree gravity'+(' · stellar lifecycle' if P['lifecycle_enabled'] else ''),seed=P['seed'],params=P,lifecycle_enabled=P['lifecycle_enabled'],
      frame_layout='xyzsmt',bytes_per_particle=24,
      description='An exponential stellar disk in a live Plummer dark-matter halo. All particles gravitate. Warm disk with approximate Jeans support; not a calibrated equilibrium galaxy.'+lifecycle_text+' Each particle is a superparticle, not a resolved star.',
      sources=['https://rebound.hanno-rein.de/c_examples/selfgravity_plummer/','https://galaxiesbook.org/chapters/II-01.-Gravitation-in-Galactic-Disks_3-Gravitational-potentials-from-disk-density-distributions.html','https://ui.adsabs.harvard.edu/abs/2001MNRAS.322..231K'])
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

def diagnostics(s,meta,baryons=None,sample=192):
    q,m=arrays(s);p=q[:,:3];v=q[:,3:];angular=np.sum(m[:,None]*np.cross(p,v),axis=0)
    kinetic=float(.5*np.sum(m[:,None]*v*v))
    if meta['mode']=='planets':
        energy=float(s.energy());sampled=False;energy_sigma=0.
    else:
        sampled=len(m)>4096;potential=0.;variance=0.
        rng=np.random.default_rng(29)
        groups=[np.arange(meta['disk_count']),np.arange(meta['disk_count'],s.N)]
        for group in groups:
            indices=rng.choice(group,min(sample,len(group)),replace=False) if sampled else group
            total=0.;terms=[]
            for i in indices:
                dist=np.sqrt(np.sum((p-p[i])**2,axis=1)+s.softening**2);dist[i]=np.inf
                term=m[i]*np.sum(m/dist);total+=term;terms.append(term)
            potential-=.5*total*len(group)/len(indices)
            if sampled:variance+=.25*len(group)**2*np.var(terms,ddof=1)/len(indices)*(1-len(indices)/len(group))
        energy=kinetic+potential;energy_sigma=float(np.sqrt(variance))
    nd=meta.get('disk_count',s.N);nh_end=nd+meta.get('halo_count',s.N-nd)
    out=dict(energy=energy,energy_sampled=sampled,energy_sigma=energy_sigma,angular_momentum=angular.tolist(),total_mass=float(np.sum(m)),
      disk_half_radius=float(np.median(np.linalg.norm(p[:nd],axis=1))),halo_half_radius=float(np.median(np.linalg.norm(p[nd:nh_end],axis=1))) if nd<nh_end else None,
      finite=bool(np.all(np.isfinite(q))),particles=s.N)
    if baryons is not None:out['lifecycle']=stellar.summary(s,baryons,m)
    return out
