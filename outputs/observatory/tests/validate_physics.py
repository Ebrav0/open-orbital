"""Numerical checks for model revision 3. Writes validation_r3.json; never overwrites validation.json."""
import sys,json,time,tempfile,importlib.util
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from physics import planets,galaxy,diagnostics,arrays,set_threads,rebound,MODEL_REVISION
import stellar
set_threads(4);results=dict(model_revision=MODEL_REVISION)
s,m,_=planets();e=s.energy();s.integrate(50);results['solar_50_year_energy_change']=abs(s.energy()/e-1)
assert results['solar_50_year_energy_change']<1e-9
s,m,_=planets(planet_mass_scale=[1,1,1,1,3,1,1,1],perturber_mass=.002,perturber_a=3.);assert s.N==10 and m['n']==10;e=s.energy();s.integrate(12);results['perturbed_12_year_energy_change']=abs(s.energy()/e-1)
assert results['perturbed_12_year_energy_change']<1e-8
# Independent analytical two-body period and circular radius.
s=rebound.Simulation();s.G=4*np.pi**2;s.add(m=1);s.add(m=3e-6,a=1);s.move_to_com();s.integrator='ias15';s.integrate(1/np.sqrt(1+3e-6));q,_=arrays(s)
results['earth_period_position_error']=float(np.linalg.norm(q[1,:3]-q[0,:3]-np.array([1,0,0])))
assert results['earth_period_position_error']<1e-9
# Revision-3 defaults must reproduce revision-2 initial conditions exactly (gravity path unchanged when lifecycle is off).
ref=Path(__file__).resolve().parents[3]/'work/observatory-data/44c528079f88/model_source.py'
if ref.exists():
    spec=importlib.util.spec_from_file_location('rev2',ref);rev2=importlib.util.module_from_spec(spec);spec.loader.exec_module(rev2)
    so,_=rev2.galaxy(2048);sn,_,_=galaxy(2048,lifecycle_enabled=False);qo,mo=arrays(so);qn,mn=arrays(sn)
    results['rev2_reproduction_max_state_difference']=float(max(np.max(np.abs(qo-qn)),np.max(np.abs(mo-mn))))
    assert results['rev2_reproduction_max_state_difference']==0.
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
# Structure knobs: a heavier disk must rotate faster; a central black hole must keep N fixed and sit at the end.
s1,_,_=galaxy(2048,lifecycle_enabled=False);s2,_,_=galaxy(2048,disk_mass=3.,lifecycle_enabled=False);q1,_=arrays(s1);q2,_=arrays(s2)
v1=np.median(np.linalg.norm(q1[:614,3:5],axis=1));v2=np.median(np.linalg.norm(q2[:614,3:5],axis=1));results['disk_speed_ratio_mass3_vs_1']=float(v2/v1);assert v2>v1
s3,m3,b3=galaxy(2048,smbh_mass=.02);assert s3.N==2048 and m3['smbh_count']==1 and abs(s3.particles[2047].m-.02)<1e-12 and b3['type'][-1]==stellar.SMBH
# A saved/reloaded integrator state must reproduce the continuation.
with tempfile.TemporaryDirectory() as td:
    p=Path(td)/'checkpoint.bin';s.save_to_file(str(p));r=rebound.Simulation(str(p));s.steps(10);r.steps(10)
    qa,_=arrays(s);qb,_=arrays(r);results['checkpoint_max_state_difference']=float(np.max(np.abs(qa-qb)))
    assert np.allclose(qa,qb,rtol=1e-11,atol=1e-11)
# Lifetimes: monotonic in mass, bounded; remnant classes by mass.
masses=np.geomspace(.08,150,200);life=stellar.lifetime_myr(masses);assert np.all(np.diff(life)<=0) and life.max()<=2e4 and life.min()>=3
rt,rm=stellar.remnant_of(np.array([1.,5.,8.,15.,20.,60.]));assert list(rt)==[stellar.WD,stellar.WD,stellar.NS,stellar.NS,stellar.BH,stellar.BH] and np.all(rm<np.array([1.,5.,8.,15.,20.,60.]))
imf=stellar.kroupa_masses(np.random.default_rng(1),200000,.08,100.);results['kroupa_sample']=dict(min=float(imf.min()),max=float(imf.max()),median=float(np.median(imf)),fraction_above_8=float(np.mean(imf>=8)))
assert .08<=imf.min() and imf.max()<=100. and .15<np.median(imf)<.6 and .002<results['kroupa_sample']['fraction_above_8']<.02
# Lifecycle on at speed 40: total mass conserved to float precision, remnant classes appear, N fixed, births and deaths logged.
s,m,b=galaxy(2048,lifecycle_speed=40,gas_fraction=.5,t_sf=.5,sn_kick_kms=50);P=m['params'];_,m0=arrays(s);M0=float(m0.sum());base=float(np.sum(m0[:m['disk_count']]))
t=time.perf_counter()
for i in range(500):
    s.steps(1);stellar.step(s,b,P,s.dt,P['seed'])
wall=time.perf_counter()-t;_,m1=arrays(s);d=diagnostics(s,m,b);lc=d['lifecycle']
results['lifecycle_speed40_2048']=dict(steps=500,wall_seconds=wall,mass_drift=abs(float(m1.sum())-M0)/M0,baryon_mass_drift=abs(lc['baryon_mass']-base)/base,counts=lc['counts'],births=lc['births_cumulative'],deaths=lc['deaths_cumulative'],supernovae=lc['supernovae_cumulative'],mass_return_failed=lc['mass_return_failed'],finite=d['finite'])
print(results['lifecycle_speed40_2048'],flush=True)
assert s.N==2048 and d['finite'] and results['lifecycle_speed40_2048']['mass_drift']<1e-6 and results['lifecycle_speed40_2048']['baryon_mass_drift']<1e-6
assert lc['births_cumulative']>0 and lc['deaths_cumulative']>0 and lc['counts']['white_dwarf']>0 and lc['counts']['neutron_star']+lc['counts']['black_hole']>0
assert np.all(m1>=0)
# Halo and SMBH slots never lifecycle.
assert np.all(b['type'][m['disk_count']:]==stellar.HALO)
# Baryon checkpoint round trip and deterministic RNG on resume: same seed + same steps_done gives identical continuation.
with tempfile.TemporaryDirectory() as td:
    stellar.save_baryons(Path(td)/'b.npz',b);b2=stellar.load_baryons(Path(td)/'b.npz');s.save_to_file(str(Path(td)/'c.bin'));r=rebound.Simulation(str(Path(td)/'c.bin'))
    assert all(np.array_equal(b[k],b2[k]) for k in('type','age','m_star','birth_time')) and b2['supernovae']==b['supernovae']
    for i in range(20):
        s.steps(1);stellar.step(s,b,P,s.dt,P['seed']);r.steps(1);stellar.step(r,b2,P,r.dt,P['seed'])
    _,ma=arrays(s);_,mb=arrays(r);results['resume_rng_max_mass_difference']=float(np.max(np.abs(ma-mb)));assert np.array_equal(b['type'],b2['type']) and results['resume_rng_max_mass_difference']==0.
out=Path(__file__).resolve().parents[1]/'validation_r3.json';out.write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
