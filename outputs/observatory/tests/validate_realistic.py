"""Model revision 6 ("Real World Physics") checks. Writes validation_r6.json (or $OBSERVATORY_TEST_REPORT).
Never rewrites validation.json / _r3 / _r4 / _r5. Run from the task root:
  PYTHONPATH="$PWD/work/openmp" work/venv/bin/python outputs/observatory/tests/validate_realistic.py
"""
import json,os,sys,time,signal,subprocess,tempfile,shutil
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import physics,stellar,realistic
from physics import galaxy,arrays,set_threads,ensure_tree_box_for_step
set_threads(4)
out={};t_all=time.time()

# 1. Stellar-population tables from the Kroupa IMF + lifetime law (literature: ~0.01 SN per Msun, R(10 Gyr) ~ 0.4-0.45).
ret,nsn=stellar.ssp_tables()
out['ssp']=dict(returned_10gyr=float(np.interp(1e4,stellar.SSP_AGES,ret)),returned_100myr=float(np.interp(100,stellar.SSP_AGES,ret)),sn_per_msun=float(nsn[-1]),
    sn_done_by_myr=float(stellar.SSP_AGES[np.searchsorted(nsn,.999*nsn[-1])]))

# 2. SPH: exact momentum conservation; two colliding clouds dissipate kinetic energy.
rng=np.random.default_rng(7)
x=np.vstack((rng.normal(size=(3000,3))*.05+[-.2,0,0],rng.normal(size=(3000,3))*.05+[.2,0,0]));v=np.zeros_like(x);v[:3000,0]=1;v[3000:,0]=-1;m=np.full(6000,1e-4)
KE0=.5*np.sum(m*np.sum(v*v,1));P0=(m[:,None]*v).sum(0);Pscale=np.sum(m*np.linalg.norm(v,axis=1));t=0.
for _ in range(300):
    a,rho,h,dv,dtc=realistic.sph(x,v,m,1e-4);dt=min(dtc,.002);v+=.5*dt*a;x+=v*dt;a,*_=realistic.sph(x,v,m,1e-4);v+=.5*dt*a;t+=dt
out['sph_collision']=dict(time=t,kinetic_energy_ratio=float(.5*np.sum(m*np.sum(v*v,1))/KE0),momentum_change_relative=float(np.linalg.norm((m[:,None]*v).sum(0)-P0)/Pscale))

# 2b. Halo speeds vs the Jeans equation (no N-body noise): 400k samples, sigma_r^2 ratio in radial shells.
from scipy.integrate import quad
def jeans_ratios(kw,eps=.04):
    Q=physics.galaxy_params(dict(realistic=True,**kw));a,Mp,re=physics._hernquist(Q);Rd=kw['disk_scale'];g=np.random.default_rng(2)
    rt=np.concatenate(([0.],np.geomspace(1e-6*a,100,20000)));mt=physics.halo_mass(rt,a,Mp,re);mt/=mt[-1];r=np.interp(g.uniform(0,1,400000),mt,rt)
    v=physics.eddington_speeds(g,r,Q,eps)
    # Jeans with the same softened potential the sampler uses: sigma_r^2(r) = (1/rho) int_r^R rho (-dPsi/dr') dr'
    rg=np.geomspace(1e-4*a,100,20000);full=physics._psi_total(rg,Q,eps)-physics.halo_psi(rg,a,Mp,re)+physics._halo_psi_softened(rg,a,Mp,re,eps)
    integrand=physics.halo_rho(rg,a,Mp,re)*-np.gradient(full,rg);tail=np.concatenate((np.cumsum((.5*(integrand[1:]+integrand[:-1])*np.diff(rg))[::-1])[::-1],[0.]))
    out={}
    for lo,hi in [(.1,.2),(.5,.7),(1.5,2),(4,5),(10,12),(30,35),(60,70)]:
        s=(r>lo)&(r<hi);rm=float(np.sqrt(lo*hi))
        out[f'{rm:.2f}']=float(np.mean(v[s]**2)/3/(np.interp(rm,rg,tail)/float(physics.halo_rho(rm,a,Mp,re))))
    return out
out['jeans_default_disk']=jeans_ratios(dict(disk_mass=1.,smbh_mass=0.,halo_mass=20.,halo_scale=4.,disk_scale=1.2))
out['jeans_compact_bh']=jeans_ratios(dict(disk_mass=3.,smbh_mass=.138,halo_mass=60.,halo_scale=1.8,disk_scale=.54))

# 2c. Star-formation law on a dense uniform gas sphere: births vs sum of 1 - exp(-eps_ff dt / t_ff) over SPH densities.
import rebound
g=np.random.default_rng(4);ns=4000;pos=g.normal(size=(ns,3));pos=pos/np.linalg.norm(pos,axis=1)[:,None]*.2*g.random(ns)[:,None]**(1/3)
sim=rebound.Simulation();sim.G=1;sim.softening=.02;physics._add_particles(sim,pos,np.zeros((ns,3)),np.full(ns,.5/ns))
bar=dict(type=np.zeros(ns,np.uint8),age=np.zeros(ns),m_star=np.zeros(ns),birth_time=np.zeros(ns),pending=np.zeros(ns),births=0,born_mass=0.,born_window_myr=0.,
    sn_total=0.,p_delivered=0.,p_unused=0.,returned=0.,supernovae=0,ssp=True)
eng=realistic.Engine(sim,dict(physics=dict(dt_initial=.01,dt_max=.02),seed=1),bar,dict(imf_mmin=.08,imf_mmax=100.))
eng._sph();dt_sf=1.;tff=np.sqrt(3*np.pi/(32*eng.rho))
expected=float(np.sum(np.where(eng.rho*realistic.NH_PER_CODE>=realistic.N_TH,1-np.exp(-realistic.EPS_FF*dt_sf/tff),0.)))
eng._form_stars(dt_sf,np.random.default_rng(5))
out['star_formation_law']=dict(median_n_h=float(np.median(eng.rho)*realistic.NH_PER_CODE),expected_births=expected,births=int(bar['births']),
    sigma=float((bar['births']-expected)/np.sqrt(expected)))

# 3. Equilibrium: isolated galaxy, 30k, t = 20 (490 Myr). Revision 5 (Plummer, approximate halo velocities) vs revision 6
#    (Hernquist + Eddington). Gas off in both so this isolates the stellar/halo initial conditions.
def lagrange(q,m,sel,c):
    r=np.linalg.norm(q[sel,:3]-c,axis=1);o=np.argsort(r);cm=np.cumsum(m[sel][o]);cm/=cm[-1]
    return [float(r[o][np.searchsorted(cm,f)]) for f in (.1,.5,.9)]
def axes(x):
    I=(x[:,:,None]*x[:,None,:]).mean(0);w=np.sort(np.linalg.eigvalsh(I))[::-1];return float(np.sqrt(w[2]/w[0]))
def run_iso(real):
    kw=dict(n=30000,n_galaxies=1,gas_fraction=0.)
    if real:s,meta,b=galaxy(realistic=True,**kw);eng=realistic.Engine(s,meta,b,meta['params'])
    else:s,meta,b=galaxy(revision=5,lifecycle_enabled=False,**kw);eng=None
    nd=meta['disk_count'];rows=[];t0=time.time()
    for k in range(21):
        if k:
            if eng:
                while k-s.t>1e-9:eng.step(k-s.t,ensure_tree_box_for_step)
            else:
                for _ in range(round(1/s.dt)):ensure_tree_box_for_step(s);s.steps(1)
        q,mm=arrays(s);c=np.average(q[:nd,:3],axis=0,weights=mm[:nd]);halo=np.zeros(len(mm),bool);halo[nd:]=True
        rows.append(lagrange(q,mm,halo,c)+[axes(q[:nd,:3]-c)])
    R=np.array(rows);ring=np.abs(R[:,:3]/R[0,:3]-1)
    return dict(softening=float(s.softening),steps=int(s.steps_done),wall_seconds=time.time()-t0,
        halo_r10_r50_r90_max_change=ring.max(0).tolist(),halo_r10_r50_r90_final_change=ring[-1].tolist(),disk_c_over_a=[R[0,3],R[-1,3]])
out['equilibrium_rev5']=run_iso(False);out['equilibrium_rev6']=run_iso(True)

# 4. Worker end to end with gas, stars and feedback; mass conservation; exact resume after SIGTERM (1 thread).
cfg=dict(mode='galaxy',n=10000,threads=1,seed=3,n_galaxies=2,g2_mass_ratio=1.,g2_sep=8.,g2_vrel=1.,g2_impact=1.,lifecycle_enabled=True,gas_fraction=.3,realistic=True,duration=.6,softening=.06,dt=.02)
tmp=Path(tempfile.mkdtemp(prefix='orbital-r6-'))
env=dict(os.environ,PYTHONPATH=os.environ.get('PYTHONPATH',''))
def start(d):
    d.mkdir(exist_ok=True);(d/'config.json').write_text(json.dumps(cfg));(d/'control.json').write_text('{"action":"run"}')
    return subprocess.Popen([sys.executable,str(HERE/'worker.py'),str(d)],cwd=HERE,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
try:
    A=tmp/'a';t0=time.time();pa=start(A);pa.wait();wa=time.time()-t0
    sa=json.loads((A/'status.json').read_text());ma=json.loads((A/'meta.json').read_text())
    B=tmp/'b';pb=start(B)
    while True:
        time.sleep(.2)
        try:
            if json.loads((B/'status.json').read_text()).get('frames',0)>=100:break
        except Exception:pass
    pb.send_signal(signal.SIGTERM);pb.wait();mid=json.loads((B/'status.json').read_text())
    pb=start(B);pb.wait();sb=json.loads((B/'status.json').read_text())
    n=ma['n'];fa=np.fromfile(A/'frames.bin','<f4').reshape(-1,n,6);fb=np.fromfile(B/'frames.bin','<f4').reshape(-1,n,6)
    lc=sa['diagnostics']['lifecycle']
    out['worker']=dict(phase=sa['phase'],error=sa.get('error'),frames=sa['frames'],steps=sa['steps'],wall_seconds=wa,model_revision=ma['model_revision'],
        softening=ma['softening'],dt_initial=ma['physics']['dt_initial'],last_step=sa.get('realistic'),
        total_mass_first=float(fa[0,:,4].astype(np.float64).sum()),total_mass_last=float(fa[-1,:,4].astype(np.float64).sum()),
        gas_mass=lc['gas_mass'],births=lc['births_cumulative'],supernovae=lc['supernovae_cumulative'],feedback_momentum=lc['feedback_momentum'],
        resume=dict(interrupted_phase=mid['phase'],interrupted_at_frame=mid['frames'],final_phase=sb['phase'],frames_identical=bool(fa.shape==fb.shape and np.array_equal(fa,fb)),
            max_position_difference=float(np.max(np.abs(fa[...,:3]-fb[...,:3]))) if fa.shape==fb.shape else None))
finally:shutil.rmtree(tmp,ignore_errors=True)

out['wall_seconds']=time.time()-t_all
w=out['worker'];e5,e6=out['equilibrium_rev5'],out['equilibrium_rev6']
checks=dict(ssp_sn_per_msun_in_0p008_0p013=.008<out['ssp']['sn_per_msun']<.013,ssp_returned_10gyr_in_0p35_0p5=.35<out['ssp']['returned_10gyr']<.5,
    sph_momentum_exact=out['sph_collision']['momentum_change_relative']<1e-12,sph_dissipates=out['sph_collision']['kinetic_energy_ratio']<.8,
    worker_complete=w['phase']=='complete',revision_6=w['model_revision']==6,mass_conserved=abs(w['total_mass_last']/w['total_mass_first']-1)<1e-5,
    resume_exact=w['resume']['frames_identical'],
    jeans_within_3pct_beyond_r0p5=all(abs(x-1)<.03 for d in (out['jeans_default_disk'],out['jeans_compact_bh']) for k,x in d.items() if float(k)>.5),
    star_formation_law_within_4sigma=abs(out['star_formation_law']['sigma'])<4)
out['checks']=checks
report=Path(os.environ.get('OBSERVATORY_TEST_REPORT',HERE/'validation_r6.json'))
report.write_text(json.dumps(out,indent=1))
print(json.dumps(out,indent=1))
if not all(checks.values()):sys.exit(1)
