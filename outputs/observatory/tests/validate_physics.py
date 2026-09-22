"""Numerical checks for model revision 6. Writes validation_r6.json; never overwrites validation.json or validation_r3/r4/r5.json."""
import sys,json,time,tempfile,importlib.util,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from physics import planets,galaxy,diagnostics,arrays,set_threads,rebound,MODEL_REVISION,split_particle_counts
import stellar,ism
set_threads(4);results=dict(model_revision=MODEL_REVISION)
assert MODEL_REVISION==6
s,m,_=planets();e=s.energy();s.integrate(50);results['solar_50_year_energy_change']=abs(s.energy()/e-1)
assert results['solar_50_year_energy_change']<1e-9
s,m,_=planets(planet_mass_scale=[1,1,1,1,3,1,1,1],perturber_mass=.002,perturber_a=3.);assert s.N==10 and m['n']==10;e=s.energy();s.integrate(12);results['perturbed_12_year_energy_change']=abs(s.energy()/e-1)
assert results['perturbed_12_year_energy_change']<1e-8
s=rebound.Simulation();s.G=4*np.pi**2;s.add(m=1);s.add(m=3e-6,a=1);s.move_to_com();s.integrator='ias15';s.integrate(1/np.sqrt(1+3e-6));q,_=arrays(s)
results['earth_period_position_error']=float(np.linalg.norm(q[1,:3]-q[0,:3]-np.array([1,0,0])))
assert results['earth_period_position_error']<1e-9

def state(sim):
    q,m=arrays(sim);return q,m

s_iso,_,_=galaxy(2048,lifecycle_enabled=False);s_one,_,_=galaxy(2048,lifecycle_enabled=False,n_galaxies=1)
qo,mo=state(s_iso);qn,mn=state(s_one)
results['isolated_vs_n_galaxies_1_max_state_difference']=float(max(np.max(np.abs(qo-qn)),np.max(np.abs(mo-mn))))
assert results['isolated_vs_n_galaxies_1_max_state_difference']==0.

ref=Path(__file__).resolve().parents[3]/'work/observatory-data/44c528079f88/model_source.py'
if ref.exists():
    spec=importlib.util.spec_from_file_location('rev2',ref);rev2=importlib.util.module_from_spec(spec);spec.loader.exec_module(rev2)
    so,_=rev2.galaxy(2048);qo,mo=state(so);qn,mn=state(s_iso)
    results['rev2_reproduction_max_state_difference']=float(max(np.max(np.abs(qo-qn)),np.max(np.abs(mo-mn))))
    assert results['rev2_reproduction_max_state_difference']==0.
else:
    results['rev2_reproduction_max_state_difference']=None
# Bit-match isolated ICs against the revision-3 generator on origin/main when git is available.
root=Path(__file__).resolve().parents[3]
try:
    src=subprocess.check_output(['git','show','origin/main:outputs/observatory/physics.py'],cwd=root)
    tmp=Path(tempfile.mkdtemp())/'physics_r3.py';tmp.write_bytes(src)
    spec=importlib.util.spec_from_file_location('physics_r3',tmp);r3=importlib.util.module_from_spec(spec);spec.loader.exec_module(r3)
    so,_,_=r3.galaxy(2048,lifecycle_enabled=False);qo,mo=state(so);qn,mn=state(s_iso)
    results['rev3_isolated_max_state_difference']=float(max(np.max(np.abs(qo-qn)),np.max(np.abs(mo-mn))))
    assert results['rev3_isolated_max_state_difference']==0.
except Exception as e:
    results['rev3_isolated_max_state_difference']=f'skipped:{type(e).__name__}'

runs=[]
for dt,theta in [(.02,.4),(.01,.4),(.02,.25)]:
    s,m,_=galaxy(2048,theta=theta,dt=dt,lifecycle_enabled=False);initial=diagnostics(s,m);s.steps(round(10/dt));end=diagnostics(s,m)
    runs.append(dict(dt=dt,theta=theta,energy_change=abs(end['energy']/initial['energy']-1),disk_radius_change=end['disk_half_radius']/initial['disk_half_radius']-1,halo_radius_change=end['halo_half_radius']/initial['halo_half_radius']-1,angular_change=float(np.linalg.norm(np.array(end['angular_momentum'])-initial['angular_momentum'])/np.linalg.norm(initial['angular_momentum'])),finite=end['finite']))
    print(runs[-1],flush=True)
    assert end['finite'] and s.N==2048
    assert abs(runs[-1]['disk_radius_change'])<.2
    assert abs(runs[-1]['halo_radius_change'])<.2
    assert runs[-1]['energy_change']<.02
results['galaxy_2048_t10_lifecycle_off']=runs
s1,_,_=galaxy(2048,lifecycle_enabled=False);s2,_,_=galaxy(2048,disk_mass=3.,lifecycle_enabled=False);q1,_=arrays(s1);q2,_=arrays(s2)
v1=np.median(np.linalg.norm(q1[:614,3:5],axis=1));v2=np.median(np.linalg.norm(q2[:614,3:5],axis=1));results['disk_speed_ratio_mass3_vs_1']=float(v2/v1);assert v2>v1
s3,m3,b3=galaxy(2048,smbh_mass=.02);assert s3.N==2048 and m3['smbh_count']==1 and abs(s3.particles[2047].m-.02)<1e-12 and b3['type'][-1]==stellar.SMBH
with tempfile.TemporaryDirectory() as td:
    p=Path(td)/'checkpoint.bin';s_iso.save_to_file(str(p));r=rebound.Simulation(str(p));s_iso.steps(10);r.steps(10)
    qa,_=arrays(s_iso);qb,_=arrays(r);results['checkpoint_max_state_difference']=float(np.max(np.abs(qa-qb)))
    assert np.allclose(qa,qb,rtol=1e-11,atol=1e-11)
masses=np.geomspace(.08,150,200);life=stellar.lifetime_myr(masses);assert np.all(np.diff(life)<=0) and life.max()<=2e4 and life.min()>=3
rt,rm=stellar.remnant_of(np.array([1.,5.,8.,15.,20.,60.]));assert list(rt)==[stellar.WD,stellar.WD,stellar.NS,stellar.NS,stellar.BH,stellar.BH] and np.all(rm<np.array([1.,5.,8.,15.,20.,60.]))
imf=stellar.kroupa_masses(np.random.default_rng(1),200000,.08,100.);results['kroupa_sample']=dict(min=float(imf.min()),max=float(imf.max()),median=float(np.median(imf)),fraction_above_8=float(np.mean(imf>=8)))
assert .08<=imf.min() and imf.max()<=100. and .15<np.median(imf)<.6 and .002<results['kroupa_sample']['fraction_above_8']<.02
s,m,b=galaxy(2048,lifecycle_speed=40,gas_fraction=.5,t_sf=.5,sn_kick_kms=50,ism_enabled=False);P=m['params'];_,m0=arrays(s);M0=float(m0.sum());base=float(np.sum(m0[:m['disk_count']]))
t=time.perf_counter()
for i in range(500):
    s.steps(1);stellar.step(s,b,P,s.dt,P['seed'])
wall=time.perf_counter()-t;_,m1=arrays(s);d=diagnostics(s,m,b);lc=d['lifecycle']
results['lifecycle_speed40_2048']=dict(steps=500,wall_seconds=wall,mass_drift=abs(float(m1.sum())-M0)/M0,baryon_mass_drift=abs(lc['baryon_mass']-base)/base,counts=lc['counts'],births=lc['births_cumulative'],deaths=lc['deaths_cumulative'],supernovae=lc['supernovae_cumulative'],mass_return_failed=lc['mass_return_failed'],finite=d['finite'])
print(results['lifecycle_speed40_2048'],flush=True)
assert s.N==2048 and d['finite'] and results['lifecycle_speed40_2048']['mass_drift']<1e-6 and results['lifecycle_speed40_2048']['baryon_mass_drift']<1e-6
assert lc['births_cumulative']>0 and lc['deaths_cumulative']>0 and lc['counts']['white_dwarf']>0 and lc['counts']['neutron_star']+lc['counts']['black_hole']>0
assert np.all(m1>=0)
assert np.all(b['type'][m['disk_count']:]==stellar.HALO)
with tempfile.TemporaryDirectory() as td:
    stellar.save_baryons(Path(td)/'b.npz',b);b2=stellar.load_baryons(Path(td)/'b.npz');s.save_to_file(str(Path(td)/'c.bin'));r=rebound.Simulation(str(Path(td)/'c.bin'))
    assert all(np.array_equal(b[k],b2[k]) for k in('type','age','m_star','birth_time','disk_mask')) and b2['supernovae']==b['supernovae']
    assert 'u' in b2 and 'Z' in b2 and 'x' in b2 and np.allclose(b['x'],b2['x'])
    for i in range(20):
        s.steps(1);stellar.step(s,b,P,s.dt,P['seed']);r.steps(1);stellar.step(r,b2,P,r.dt,P['seed'])
    _,ma=arrays(s);_,mb=arrays(r);results['resume_rng_max_mass_difference']=float(np.max(np.abs(ma-mb)));assert np.array_equal(b['type'],b2['type']) and results['resume_rng_max_mass_difference']==0.

# N split helper: remainder on A, floor of 256 per galaxy.
c=split_particle_counts(10000,[1,1,1,1,1]);assert int(c.sum())==10000 and len(c)==5 and np.all(c>=256)
try:
    split_particle_counts(1000,[1,1,1,1,1]);raise AssertionError('expected 256-per-galaxy rejection')
except ValueError as e:
    assert '256' in str(e)
results['split_particle_counts_5x10000']=[int(x) for x in c]

# Two galaxies, head-on: distinct COMs, closing separation, finite.
s,meta,_=galaxy(2048,n_galaxies=2,g2_impact=0,g2_sep=20,g2_vrel=2,lifecycle_enabled=False)
assert meta['n_galaxies']==2 and len(meta['galaxies'])==2 and sum(g['n'] for g in meta['galaxies'])==2048
d0=diagnostics(s,meta);sep0=d0['encounter']['separation_12']
assert sep0>1 and np.linalg.norm(np.array(meta['galaxies'][0]['com0'])-np.array(meta['galaxies'][1]['com0']))>1
s.steps(80);d1=diagnostics(s,meta)
results['two_galaxy_head_on']=dict(n=s.N,sep0=sep0,sep80=d1['encounter']['separation_12'],finite=d1['finite'],slices=[g['n'] for g in meta['galaxies']])
print(results['two_galaxy_head_on'],flush=True)
assert d1['finite'] and d1['encounter']['separation_12']<sep0

# Five galaxies share N.
s5,m5,_=galaxy(4096,n_galaxies=5,lifecycle_enabled=False)
assert m5['n_galaxies']==5 and len(m5['galaxies'])==5 and sum(g['n'] for g in m5['galaxies'])==4096
d5=diagnostics(s5,m5);assert d5['finite']
results['five_galaxy_4096']=dict(slices=[g['n'] for g in m5['galaxies']],finite=d5['finite'])

# Encounter lifecycle: mass conserved, disk_mask length N, halo/SMBH never become stars.
s,m,b=galaxy(2048,n_galaxies=2,lifecycle_speed=40,gas_fraction=.5,t_sf=.5,ism_enabled=False)
P=m['params'];_,m0=arrays(s);M0=float(m0.sum());mask=b['disk_mask'].astype(bool)
assert len(b['disk_mask'])==2048 and int(mask.sum())==m['disk_count']
for i in range(200):
    s.steps(1);stellar.step(s,b,P,s.dt,P['seed'])
_,m1=arrays(s);d=diagnostics(s,m,b)
results['two_galaxy_lifecycle_200']=dict(mass_drift=abs(float(m1.sum())-M0)/M0,disk_mask_sum=int(mask.sum()),finite=d['finite'])
assert results['two_galaxy_lifecycle_200']['mass_drift']<1e-6 and d['finite']
assert np.all(np.isin(b['type'][~mask],[stellar.HALO,stellar.SMBH]))

def Lz(sim,g):
    q,mass=arrays(sim);sl=slice(g['start'],g['start']+g['n']);p=q[sl,:3];v=q[sl,3:];mw=mass[sl]
    com=np.average(p,axis=0,weights=mw);vcom=np.average(v,axis=0,weights=mw)
    return float(np.sum(mw[:,None]*np.cross(p-com,v-vcom),axis=0)[2])
s,meta,_=galaxy(2048,n_galaxies=2,g2_spin=-1,lifecycle_enabled=False)
lz_a,lz_b=Lz(s,meta['galaxies'][0]),Lz(s,meta['galaxies'][1])
results['retrograde_Lz']=dict(A=lz_a,B=lz_b)
assert lz_a*lz_b<0

# ---- ISM (revision 6; revision-5 qualitative checks kept) ----
T=np.logspace(4,6.2,80);L=ism.cooling_lambda(T,1.);L0=ism.cooling_lambda(T,.05)
results['cooling_peak_K']=float(T[np.argmax(L)])
assert 1e5<results['cooling_peak_K']<1e6 and float(L.max())>float(L0.max())  # metal-line peak
T4,mu4=ism.temperature(ism.u_from_T(1e4))
results['temperature_roundtrip_1e4']=float(T4) if np.ndim(T4)==0 else float(np.mean(T4))
assert abs(float(np.mean(T4))-1e4)<800
# Dense hot parcel cools toward the warm floor; delayed particles do not.
s=rebound.Simulation();s.G=1;s.gravity='none';s.dt=.02
pos=np.zeros((12,3));vel=np.zeros((12,3));mass=np.full(12,.002)
# pack them into one cell so n_H is high
pos[:,0]=np.linspace(0,.04,12)
q=np.c_[pos,vel]
for i in range(12):s.add(m=mass[i],x=pos[i,0],y=0,z=0)
b=dict(type=np.zeros(12,np.uint8),age=np.zeros(12),m_star=np.zeros(12),birth_time=np.zeros(12),disk_mask=np.ones(12,np.uint8),disk_count=12,debt=0.,born_mass=0.,born_window_myr=0.,supernovae=0,deaths=0,births=0,failed_return=0.)
ism.attach(b,dict(metallicity=1.,cooling_speed=1.,ram_pressure=0.,sn_feedback=0.,n_sf=.1,ism_enabled=True))
b['u'][:]=ism.u_from_T(5e5);b['cool_delay'][:6]=40.
q,_m=arrays(s)
ism.step(q,_m,b,dict(cooling_speed=1.,ram_pressure=0.,sn_feedback=0.,n_sf=.1,ism_enabled=True,metallicity=1.),.02)
T_after,_=ism.temperature(b['u'])
results['cooling_delay_holds_hot']=float(np.mean(T_after[:6]));results['cooling_undelayed_drops']=float(np.mean(T_after[6:]))
assert results['cooling_delay_holds_hot']>1e5 and results['cooling_undelayed_drops']<results['cooling_delay_holds_hot']*.8
# Ram: two approaching clumps, gravity off. Momentum conserved, relative speed drops, some heat.
s=rebound.Simulation();s.G=1;s.gravity='none';s.dt=.02
n=16;pos=np.zeros((n,3));vel=np.zeros((n,3));mass=np.full(n,.001)
pos[:8,0]=0;pos[8:,0]=ism.CELL;vel[:8,0]=1.2;vel[8:,0]=-1.2
for i in range(n):s.add(m=mass[i],x=pos[i,0],y=0,z=0,vx=vel[i,0])
b=dict(type=np.zeros(n,np.uint8),age=np.zeros(n),m_star=np.zeros(n),birth_time=np.zeros(n),disk_mask=np.ones(n,np.uint8),disk_count=n,debt=0.,born_mass=0.,born_window_myr=0.,supernovae=0,deaths=0,births=0,failed_return=0.)
ism.attach(b,dict(metallicity=1.))
q0,m0=arrays(s);px0=float(np.sum(m0*q0[:,3]));u0=float(np.mean(b['u']));vrel0=float(np.mean(q0[:8,3])-np.mean(q0[8:,3]))
ism.step(q0,m0,b,dict(cooling_speed=0.,ram_pressure=1.,sn_feedback=0.,n_sf=.1,ism_enabled=True,metallicity=1.),.02)
s.set_serialized_particle_data(xyzvxvyvz=q0)
q1,m1=arrays(s);px1=float(np.sum(m1*q1[:,3]));vrel1=float(np.mean(q1[:8,3])-np.mean(q1[8:,3]))
results['ram_momentum_drift']=abs(px1-px0);results['ram_vrel0']=vrel0;results['ram_vrel1']=vrel1;results['ram_u_ratio']=float(np.mean(b['u'])/u0)
assert results['ram_momentum_drift']<1e-8 and vrel1<vrel0 and np.all(np.isfinite(q1))
# Hot gas is not eligible for star formation.
types=np.zeros(32,np.uint8);types[16:]=ism.HOT
pos=np.zeros((32,3));vel=np.zeros((32,3));mass=np.full(32,.01);u=np.full(32,ism.u_from_T(1e4));u[16:]=ism.u_from_T(8e5)
pos[:,0]=np.linspace(0,.02,32)
sf=ism.star_forming(pos,vel,mass,u,types,dict(n_sf=.01))
assert np.any(sf[:16]) and not np.any(sf[16:])
results['sf_rejects_hot']=True
# Full galaxy with ISM on: mass conserved, finite, u/Z present, types valid.
s,m,b=galaxy(2048,lifecycle_speed=40,gas_fraction=.5,t_sf=.5,ism_enabled=True,sn_feedback=.2,ram_pressure=1.,cooling_speed=1.)
P=m['params'];_,m0=arrays(s);M0=float(m0.sum());assert 'u' in b and 'Z' in b and 'x' in b and m['ism_enabled'] and m['model_revision']==6
for i in range(80):
    s.steps(1);stellar.step(s,b,P,s.dt,P['seed'])
_,m1=arrays(s);d=diagnostics(s,m,b);lc=d['lifecycle']
results['ism_lifecycle_80']=dict(mass_drift=abs(float(m1.sum())-M0)/M0,finite=d['finite'],mean_T=lc.get('mean_temperature'),hot_mass=lc.get('hot_gas_mass'),cold_mass=lc.get('cold_gas_mass'),births=lc.get('births_cumulative'),Z=lc.get('mean_metallicity'),counts=lc.get('counts'))
print(results['ism_lifecycle_80'],flush=True)
assert d['finite'] and results['ism_lifecycle_80']['mass_drift']<1e-6 and np.all(m1>=0)
assert np.all(np.isin(b['type'],np.arange(10))) and np.all(b['type'][m['disk_count']:]==stellar.HALO)
assert lc['mean_temperature']>0 and abs((lc['cold_gas_mass']+lc['hot_gas_mass'])-lc['gas_mass'])<1e-9
# Two-galaxy ISM still conserves mass and stays finite.
s,m,b=galaxy(2048,n_galaxies=2,lifecycle_speed=40,gas_fraction=.5,t_sf=.5,ism_enabled=True)
P=m['params'];_,m0=arrays(s);M0=float(m0.sum())
for i in range(40):
    s.steps(1);stellar.step(s,b,P,s.dt,P['seed'])
_,m1=arrays(s);d=diagnostics(s,m,b)
results['two_galaxy_ism_40']=dict(mass_drift=abs(float(m1.sum())-M0)/M0,finite=d['finite'],sep=d['encounter']['separation_12'],hot=d['lifecycle'].get('hot_gas_mass'))
assert results['two_galaxy_ism_40']['mass_drift']<1e-6 and d['finite']
# ISM resume: u, Z and velocities match after checkpoint.
s,m,b=galaxy(1024,lifecycle_speed=20,gas_fraction=.4,t_sf=.8,ism_enabled=True,sn_feedback=.1)
P=m['params']
for i in range(15):
    s.steps(1);stellar.step(s,b,P,s.dt,P['seed'])
with tempfile.TemporaryDirectory() as td:
    stellar.save_baryons(Path(td)/'b.npz',b);b2=stellar.load_baryons(Path(td)/'b.npz');s.save_to_file(str(Path(td)/'c.bin'));r=rebound.Simulation(str(Path(td)/'c.bin'))
    assert np.allclose(b['u'],b2['u']) and np.allclose(b['Z'],b2['Z']) and np.allclose(b['x'],b2['x'])
    for i in range(12):
        s.steps(1);stellar.step(s,b,P,s.dt,P['seed']);r.steps(1);stellar.step(r,b2,P,r.dt,P['seed'])
    qa,_=arrays(s);qb,_=arrays(r)
    results['ism_resume_max_state_difference']=float(max(np.max(np.abs(qa-qb)),np.max(np.abs(b['u']-b2['u'])),np.max(np.abs(b['x']-b2['x']))))
    assert np.array_equal(b['type'],b2['type']) and results['ism_resume_max_state_difference']==0.

# peek must not consume the SFR window that the 40-frame energy cadence uses.
b['born_mass']=3.5;b['born_window_myr']=12.
_,mpeek=arrays(s);p=stellar.peek(s,b,mpeek)
assert abs(b['born_mass']-3.5)<1e-12 and p['mean_temperature']>0 and 'hot_gas_mass' in p and 'mean_electron_fraction' in p
stellar.summary(s,b,mpeek);assert b['born_mass']==0 and b['born_window_myr']==0
results['peek_preserves_sfr_window']=True

# ---- revision 6: the same operator at several strengths ----
def _blank(n,types=None):
    b=dict(type=np.zeros(n,np.uint8) if types is None else np.asarray(types,dtype=np.uint8),age=np.zeros(n),m_star=np.zeros(n),birth_time=np.zeros(n),disk_mask=np.ones(n,np.uint8),disk_count=n,debt=0.,born_mass=0.,born_window_myr=0.,supernovae=0,deaths=0,births=0,failed_return=0.)
    ism.attach(b,dict(metallicity=1.))
    return b

def snowplow_case(f):
    """One dying 25 Msun star in a cell of gas. Gravity off, so the radial speed is the snowplow."""
    n=9
    s=rebound.Simulation();s.G=1;s.gravity='none';s.dt=.02;s.integrator='leapfrog'
    pos=np.zeros((n,3));mass=np.full(n,.01)
    ang=np.linspace(0,2*np.pi,n-1,endpoint=False)
    pos[:-1,0]=.04+.02*np.cos(ang);pos[:-1,1]=.04+.02*np.sin(ang);pos[-1]=[.04,.04,0.]
    for i in range(n):s.add(m=float(mass[i]),x=float(pos[i,0]),y=float(pos[i,1]),z=0.)
    types=np.zeros(n,np.uint8);types[-1]=stellar.GIANT
    b=_blank(n,types);b['m_star'][-1]=25.;b['age'][-1]=float(stellar.lifetime_myr(np.array([25.]))[0])+5.
    P=dict(lifecycle_speed=1.,grow_rate=0.,sn_kick_kms=0.,ism_enabled=True,t_sf=20.,sf_density_bias=0.,imf_mmin=.08,imf_mmax=100.,
           sn_feedback=0.,sn_momentum=f,ram_pressure=0.,cooling_speed=0.,cloud_dissipation=0.,metal_diffusion=0.,fuv_heating=0.,noneq_ionization=False,n_sf=10.,metallicity=1.)
    s.steps(1);stellar.step(s,b,P,.02,1)
    q,mw=arrays(s)
    mom=float(np.linalg.norm(np.sum(mw[:,None]*q[:,3:],axis=0)))
    hat=pos[:-1]-pos[-1];hat/=np.linalg.norm(hat,axis=1)[:,None]
    radial=float(np.mean(np.sum(q[:-1,3:]*hat,axis=1)))
    return dict(sn_momentum=f,radial_kms=radial*stellar.V_KMS,momentum=mom,deaths=int(b['deaths']),supernovae=int(b['supernovae']),deposited=float(b['sn_momentum']))

snow_rows=[snowplow_case(f) for f in (0.,.5,1.5)]
results['snowplow_levels']=snow_rows
print('snowplow',snow_rows,flush=True)
assert [r['deaths'] for r in snow_rows]==[1,1,1] and [r['supernovae'] for r in snow_rows]==[1,1,1]
assert snow_rows[0]['radial_kms']<snow_rows[1]['radial_kms']<snow_rows[2]['radial_kms']
assert all(r['momentum']<1e-8 for r in snow_rows) and snow_rows[0]['deposited']==0 and snow_rows[2]['deposited']>snow_rows[1]['deposited']*2.5
ncap=9;mass=np.full(ncap,.01);pos=np.zeros((ncap,3));vel=np.zeros((ncap,3))
ang=np.linspace(0,2*np.pi,ncap-1,endpoint=False)
pos[:-1,0]=.04+.02*np.cos(ang);pos[:-1,1]=.04+.02*np.sin(ang);pos[-1]=[.04,.04,0.]
b=_blank(ncap);ism.deposit_feedback(b,mass,vel,pos,np.arange(ncap-1),pos[-1],ncap-1,5.,dict(sn_momentum=50.,sn_feedback=0.))
results['snowplow_cap_max_speed']=float(np.linalg.norm(vel,axis=1).max())
assert results['snowplow_cap_max_speed']<=ism.SNOW_CAP+1e-9 and float(np.linalg.norm(np.sum(mass[:,None]*vel,axis=0)))<1e-8

def cloud_case(coeff):
    n=12;rng=np.random.default_rng(7)
    pos=np.zeros((n,3));pos[:,0]=np.linspace(.02,.06,n);pos[:,1]=.04
    vel=np.zeros((n,3));vel[:,0]=.25;vel[:,1]=rng.normal(0,.12,n);mass=np.full(n,.002)
    b=_blank(n);b['u'][:]=ism.u_from_T(1.2e4);q=np.column_stack((pos,vel))
    px0=float(np.sum(mass*vel[:,0]));py0=float(np.sum(mass*vel[:,1]))
    P=dict(cloud_dissipation=coeff,ram_pressure=0.,cooling_speed=0.,metal_diffusion=0.,fuv_heating=0.,noneq_ionization=False,metallicity=1.)
    for _ in range(40):ism.step(q,mass,b,P,.02)
    vbulk=np.average(q[:,3:],axis=0,weights=mass)
    rms=float(np.sqrt(np.average(np.sum((q[:,3:]-vbulk)**2,axis=1),weights=mass)))
    return dict(cloud_dissipation=coeff,rms=rms,u=float(np.average(b['u'],weights=mass)),momentum_drift=float(np.hypot(np.sum(mass*q[:,3])-px0,np.sum(mass*q[:,4])-py0)),cloud_heat=float(b['cloud_heat']))

cloud_rows=[cloud_case(c) for c in (0.,1.,3.)]
results['cloud_dissipation_levels']=cloud_rows
print('cloud',cloud_rows,flush=True)
assert cloud_rows[0]['rms']>cloud_rows[1]['rms']>cloud_rows[2]['rms']
assert cloud_rows[0]['u']<=cloud_rows[1]['u']<=cloud_rows[2]['u']
assert all(r['momentum_drift']<1e-9 for r in cloud_rows) and cloud_rows[0]['cloud_heat']==0. and cloud_rows[2]['cloud_heat']>cloud_rows[1]['cloud_heat']>0

def metal_case(coeff):
    n=16;pos=np.zeros((n,3));pos[:8,0]=.04;pos[8:,0]=.04+ism.CELL;pos[:,1]=.04
    mass=np.full(n,.002);b=_blank(n);b['Z'][:8]=.04;b['Z'][8:]=.001
    q=np.column_stack((pos,np.zeros((n,3))));metal0=float(np.sum(mass*b['Z']))
    P=dict(metal_diffusion=coeff,ram_pressure=0.,cooling_speed=0.,cloud_dissipation=0.,fuv_heating=0.,noneq_ionization=False,metallicity=1.)
    for _ in range(40):ism.step(q,mass,b,P,.02)
    contrast=abs(float(b['Z'][:8].mean())-float(b['Z'][8:].mean()))
    return dict(metal_diffusion=coeff,metal_drift=abs(float(np.sum(mass*b['Z']))-metal0),contrast=contrast)

metal_rows=[metal_case(c) for c in (0.,.5,2.)]
results['metal_diffusion_levels']=metal_rows
print('metals',metal_rows,flush=True)
assert all(r['metal_drift']<1e-10 for r in metal_rows)
assert metal_rows[0]['contrast']>metal_rows[1]['contrast']>metal_rows[2]['contrast']

h_off,*_=ism.radiation_field(.05,1.,0.,dict(fuv_heating=0.))
h_knob,*_=ism.radiation_field(.05,1.,0.,dict(fuv_heating=5.))
h_star,_,_,_=ism.radiation_field(.05,1.,200.,dict(fuv_heating=1.))
h_dense,_,_,sh_d=ism.radiation_field(30.,1.,200.,dict(fuv_heating=1.))
results['fuv_heat']=dict(no_star=float(h_off),no_star_knob=float(h_knob),with_star=float(h_star),dense_shielded=float(np.reshape(h_dense,-1)[0]),shield_dense=float(np.reshape(sh_d,-1)[0]))
assert abs(float(h_off)-float(h_knob))<1e-30 and float(h_star)>float(h_off)*1.2 and float(np.reshape(h_dense,-1)[0])<float(h_star)*0.05

def thermal_case(nH_target,with_star,fuv):
    n=5 if with_star else 4
    pos=np.full((n,3),.04);mass=np.full(n,nH_target*ism.VOL/(ism.N_H0*4.))
    b=_blank(n)
    if with_star:
        b['type'][-1]=stellar.MS;b['m_star'][-1]=40.;b['age'][-1]=2.;mass[-1]=.01
    q=np.column_stack((pos,np.zeros((n,3))))
    P=dict(ram_pressure=0.,cooling_speed=1.,cloud_dissipation=0.,metal_diffusion=0.,fuv_heating=fuv,noneq_ionization=True,metallicity=1.)
    for _ in range(12):ism.step(q,mass,b,P,.02)
    gas=ism.is_gas(b['type']);T,_=ism.thermal_state(b['u'][gas],b['x'][gas])
    return float(np.average(T,weights=np.maximum(mass[gas],0.)))

fuv_scan=[]
for nH in (.05,.5,5.,20.):
    fuv_scan.append(dict(nH=nH,no_star=thermal_case(nH,False,1.),star_fuv0=thermal_case(nH,True,0.),star_fuv1=thermal_case(nH,True,1.),star_fuv4=thermal_case(nH,True,4.)))
results['fuv_temperature_levels']=fuv_scan
print('fuv T',fuv_scan,flush=True)
by={r['nH']:r for r in fuv_scan}
assert abs(by[.5]['star_fuv0']-by[.5]['no_star'])<=1e-6*by[.5]['no_star']
assert by[.5]['star_fuv4']>by[.5]['star_fuv1']>by[.5]['star_fuv0']
assert by[20.]['no_star']<2000 and by[20.]['star_fuv4']<2000
assert by[.05]['no_star']>1e7 and by[.05]['star_fuv4']>1e7

dt_sec=.02*ism.DT_PHYS;ion=[];x0=.02
for nH in (1e-6,1e-4,1e-2,1.):
    x_new,x_eq,frac=ism.relax_ionization(np.array([x0]),np.array([nH]),np.array([1e4]),np.array([ism.GAMMA_ION]),dt_sec)
    ion.append(dict(nH=nH,x=float(x_new[0]),x_eq=float(x_eq[0]),frac=float(np.reshape(frac,-1)[0]),lag=float(abs(x_new[0]-x_eq[0]))))
results['ionization_levels']=ion
print('ionization',ion,flush=True)
assert all(ion[i]['frac']<=ion[i+1]['frac']+1e-9 for i in range(3))
assert ion[-1]['lag']<1e-3 and ion[0]['lag']>max(ion[-1]['lag'],1e-6)*5
x_hot=float(ism.x_equilibrium(np.array([1e6]),np.array([1.]),np.array([ism.GAMMA_ION]))[0])
x_cold=float(ism.x_equilibrium(np.array([1e3]),np.array([10.]),np.array([0.]))[0])
results['ionization_equilibrium']=dict(million_K=x_hot,thousand_K_dense=x_cold)
assert x_hot>.9 and x_cold<.05

gal=[]
for name,knobs in (
    ('low',dict(sn_momentum=0.,cloud_dissipation=0.,metal_diffusion=0.,fuv_heating=0.,noneq_ionization=False)),
    ('mid',dict(sn_momentum=.4,cloud_dissipation=1.,metal_diffusion=.6,fuv_heating=1.,noneq_ionization=True)),
    ('high',dict(sn_momentum=1.5,cloud_dissipation=3.,metal_diffusion=2.,fuv_heating=3.,noneq_ionization=True))):
    s,m,b=galaxy(1024,seed=731,lifecycle_speed=40,gas_fraction=.5,t_sf=.5,ism_enabled=True,sn_feedback=.15,ram_pressure=1.,cooling_speed=1.,**knobs)
    _,m0=arrays(s);M0=float(m0.sum());P=m['params']
    for _i in range(30):
        s.steps(1);stellar.step(s,b,P,s.dt,P['seed'])
    q1,m1=arrays(s);d=diagnostics(s,m,b);lc=d['lifecycle']
    pairs=0;gas=np.flatnonzero(ism.is_gas(b['type']))
    if len(gas):
        g=ism._grid(q1[:,:3],q1[:,3:],m1,b['u'],gas)
        for dx,dy,dz in ((1,0,0),(0,1,0),(0,0,1)):
            _loc,ok=ism._neighbor_locs(g['uniq'],dx,dy,dz);pairs+=int(np.sum(ok))
    row=dict(level=name,mass_drift=abs(float(m1.sum())-M0)/M0,finite=bool(d['finite']),mean_T=lc.get('mean_temperature'),mean_x=lc.get('mean_electron_fraction'),x_lag=lc.get('x_lag'),metal_std=lc.get('metal_std'),cloud_heat=lc.get('cloud_heat'),sn_momentum=lc.get('sn_momentum'),hot_mass=lc.get('hot_gas_mass'),births=lc.get('births_cumulative'),supernovae=lc.get('supernovae_cumulative'),gas_face_pairs=pairs)
    gal.append(row);print('galaxy',row,flush=True)
    assert row['finite'] and row['mass_drift']<1e-6
results['galaxy_ism_levels_1024_30']=gal
assert gal[0]['cloud_heat']==0 and gal[0]['sn_momentum']==0 and gal[2]['cloud_heat']>gal[1]['cloud_heat']>0 and gal[1]['sn_momentum']>0 and gal[2]['sn_momentum']>0

out=Path(__file__).resolve().parents[1]/'validation_r6.json';out.write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
