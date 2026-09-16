"""CPU models for the local observatory. No remote services are used."""
import os
os.environ.setdefault('OMP_NUM_THREADS','8')
os.environ.setdefault('OMP_WAIT_POLICY','PASSIVE')
import ctypes,math
import numpy as np
import rebound

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

def galaxy(n=100000,seed=731,theta=.4,dt=.02):
    """Live Plummer halo + light exponential stellar disk; approximate equilibrium.
    Units: G=1, mass=1e10 solar masses, length=3 kpc, time=24.50 Myr.
    No artificial spiral pattern, damping, prescribed orbits, or frozen halo.
    """
    rng=np.random.default_rng(seed);nd=int(n*.3);nh=n-nd
    # Truncate only the extreme tail at 100 code lengths (~300 kpc).
    u=rng.uniform(1e-9,(100**3/(100**2+4**2)**1.5),nh)
    r=4/np.sqrt(u**(-2/3)-1);hp=directions(rng,nh)*r[:,None]
    # Plummer distribution function: p(q) proportional q^2 (1-q^2)^(7/2).
    q=np.empty(nh);done=0
    while done<nh:
        candidate=rng.random((nh-done)*3+16);y=rng.random(len(candidate))*.1
        good=candidate[y<candidate**2*(1-candidate**2)**3.5]
        k=min(len(good),nh-done);q[done:done+k]=good[:k];done+=k
    hv=directions(rng,nh)*(q*np.sqrt(2*20/np.sqrt(r*r+16)))[:,None]
    R=rng.gamma(2,1.2,nd)
    while np.any(R>10):
        mask=R>10;R[mask]=rng.gamma(2,1.2,np.sum(mask))
    phi=rng.uniform(0,2*np.pi,nd);z=rng.normal(0,.08,nd)
    dp=np.column_stack((R*np.cos(phi),R*np.sin(phi),z))
    # Halo circular force + spherical enclosed-mass approximation for the light disk.
    menc=1-(1+R/1.2)*np.exp(-R/1.2)
    vc=np.sqrt(20*R*R/(R*R+16)**1.5+menc/np.maximum(R,.001))
    dv=np.column_stack((-vc*np.sin(phi),vc*np.cos(phi),np.zeros(nd)))
    dv+=rng.normal(size=(nd,3))*np.array([.035,.035,.025])
    pos=np.vstack((dp,hp));vel=np.vstack((dv,hv));mass=np.r_[np.full(nd,1/nd),np.full(nh,20/nh)]
    s=rebound.Simulation();s.G=1;s.dt=dt;s.integrator='leapfrog';s.softening=.06
    s.root_size=1024;s.N_root_x=s.N_root_y=s.N_root_z=1;s.gravity='tree';s.opening_angle2=theta**2
    for p,v,m in zip(pos,vel,mass):s.add(m=m,x=p[0],y=p[1],z=p[2],vx=v[0],vy=v[1],vz=v[2])
    s.move_to_com()
    meta=dict(mode='galaxy',n=n,disk_count=nd,halo_count=nh,title='Isolated disk + live halo',length_unit='kpc',length_scale=3,time_unit='Myr',time_scale=24.50,mass_unit_solar=1e10,theta=theta,softening=.06,dt=dt,integrator='Leapfrog · tree gravity',seed=seed,
      description='A light exponential stellar disk in a live Plummer dark-matter halo. All particles gravitate. Approximate equilibrium; no gas, star formation, or close-binary physics.',sources=['https://rebound.hanno-rein.de/c_examples/selfgravity_plummer/'])
    return s,meta

def planets(jupiter_mass=1):
    s=rebound.Simulation();s.G=4*math.pi**2;s.integrator='ias15';s.add(m=1)
    for name,m,a,e,inc,L,peri,node in PLANETS:
        if name=='Jupiter':m*=jupiter_mass
        s.add(primary=s.particles[0],m=m,a=a,e=e,inc=math.radians(inc),Omega=math.radians(node),omega=math.radians(peri-node),M=math.radians(L-peri))
    s.move_to_com()
    bodies=[dict(name='Sun',mass=1,a=0,color='#ffd092')]+[dict(name=p[0],mass=p[1]*(jupiter_mass if p[0]=='Jupiter' else 1),a=p[2],e=p[3],inc=p[4],L=p[5],peri=p[6],node=p[7],color=c) for p,c in zip(PLANETS,['#b7a798','#e5c795','#76c6e7','#d98462','#d2b196','#e0cf9e','#9bd5ce','#6e91df'])]
    return s,dict(mode='planets',n=9,title='Solar System' if jupiter_mass==1 else f'Solar System · Jupiter {jupiter_mass}×',bodies=bodies,length_unit='AU',length_scale=1,time_unit='yr',time_scale=1,integrator='IAS15 · direct gravity',jupiter_mass=jupiter_mass,description='Newtonian Sun + eight planetary bodies, initialized from JPL approximate J2000 elements and rounded mass ratios. Earth includes the Moon. Not a current ephemeris. Planet sizes are enlarged for visibility; orbital distances are linear.',sources=['https://ssd.jpl.nasa.gov/planets/approx_pos.html','https://ssd.jpl.nasa.gov/planets/phys_par.html'])

def diagnostics(s,meta,sample=192):
    q,m=arrays(s);p=q[:,:3];v=q[:,3:];angular=np.sum(m[:,None]*np.cross(p,v),axis=0)
    kinetic=float(.5*np.sum(m[:,None]*v*v))
    if meta['mode']=='planets':
        energy=float(s.energy());sampled=False
    else:
        sampled=len(m)>4096;potential=0.
        rng=np.random.default_rng(29)
        groups=[np.arange(meta['disk_count']),np.arange(meta['disk_count'],s.N)]
        for group in groups:
            indices=rng.choice(group,min(sample,len(group)),replace=False) if sampled else group
            total=0.
            for i in indices:
                dist=np.sqrt(np.sum((p-p[i])**2,axis=1)+s.softening**2);dist[i]=np.inf
                total+=m[i]*np.sum(m/dist)
            potential-=.5*total*len(group)/len(indices)
        energy=kinetic+potential
    nd=meta.get('disk_count',s.N)
    return dict(energy=energy,energy_sampled=sampled,angular_momentum=angular.tolist(),disk_half_radius=float(np.median(np.linalg.norm(p[:nd],axis=1))),halo_half_radius=float(np.median(np.linalg.norm(p[nd:],axis=1))) if nd<s.N else None,finite=bool(np.all(np.isfinite(q))),particles=s.N)
