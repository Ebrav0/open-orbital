"""1M-particle sustainability checks. Writes validation_1m.json. Does not overwrite validation.json / r3 / r4."""
import os,sys,json,time,tempfile,traceback
from pathlib import Path
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
os.environ.setdefault('OMP_NUM_THREADS','8')
os.environ.setdefault('OMP_WAIT_POLICY','PASSIVE')
import numpy as np
from physics import galaxy,arrays,apply_tree_box,TREE_ROOT_DEFAULT,MODEL_REVISION,set_threads
import worker

set_threads(8)
results=dict(model_revision=MODEL_REVISION,n=1000000)
assert MODEL_REVISION==5

# Isolated ICs must keep the revision-4 tree box so small-N energy tests stay comparable.
s2048,_,_=galaxy(2048,lifecycle_enabled=False)
assert s2048.root_size==TREE_ROOT_DEFAULT
q,_=arrays(s2048);assert float(np.max(np.abs(q[:,:3])))<0.4*s2048.root_size
results['small_n_keeps_root_1024']=True

# Particles that would leave the default box: grow the root and continue integrating.
s_esc,_,_=galaxy(2048,lifecycle_enabled=False)
s_esc.particles[10].x=600
try:
    s_esc.steps(1)
    raise AssertionError('expected a tree-box error at x=600')
except RuntimeError as e:
    assert 'outside of simulation box' in str(e).lower(),e
    apply_tree_box(s_esc,margin=8.0)
    s_esc.steps(1)
results['box_expand_after_escape']=True
results['expanded_root']=float(s_esc.root_size)
assert s_esc.root_size>TREE_ROOT_DEFAULT
q,_=arrays(s_esc);assert bool(np.all(np.isfinite(q)))

# 1M live tree: init + sustained steps (not a calibrated galaxy, not a 120 h proof).
t0=time.perf_counter()
s,meta,b=galaxy(1000000,lifecycle_enabled=False,threads=8)
init_s=time.perf_counter()-t0
q,m=arrays(s)
results['init_seconds']=init_s
results['n_loaded']=int(s.N)
results['root_size']=float(s.root_size)
results['max_abs_position']=float(np.max(np.abs(q[:,:3])))
results['mass_sum']=float(m.sum())
assert s.N==1000000 and b is None
assert results['max_abs_position']<0.5*s.root_size
s.steps(2)  # warmup
t0=time.perf_counter()
n_steps=20
s.steps(n_steps)
step_s=time.perf_counter()-t0
q,_=arrays(s)
results['sustained_steps']=n_steps
results['sustained_seconds']=step_s
results['seconds_per_step']=step_s/n_steps
results['finite_after_steps']=bool(np.all(np.isfinite(q)))
assert results['finite_after_steps']
assert results['seconds_per_step']<15.0  # generous; 8-thread 1M sphere was ~2.3 s/step

# Real worker path: short 1M run in an isolated folder (duration 0.4 → 20 leapfrog steps).
td=tempfile.TemporaryDirectory(prefix='orbital-1m-')
folder=Path(td.name)/'million'
folder.mkdir()
cfg=dict(mode='galaxy',n=1000000,threads=8,duration=.4,dt=.02,seed=731,lifecycle_enabled=False,
         disk_mass=1,halo_mass=20,disk_fraction=.3,disk_scale=1.2,disk_thickness=.08,halo_scale=4,warmth=1,
         smbh_mass=0,bulge_mass=0,disk_inclination=0,disk_truncation=7,n_galaxies=1,notes='1M sustain test')
(folder/'config.json').write_text(json.dumps(cfg))
(folder/'control.json').write_text(json.dumps(dict(action='run')))
t0=time.perf_counter()
try:
    worker.run(folder)
except Exception:
    traceback.print_exc()
    raise
worker_s=time.perf_counter()-t0
status=json.loads((folder/'status.json').read_text())
meta=json.loads((folder/'meta.json').read_text())
results['worker_seconds']=worker_s
results['worker_phase']=status['phase']
results['worker_frames']=status.get('frames',0)
results['worker_steps']=status.get('steps',0)
results['worker_error']=status.get('error')
results['worker_root']=meta.get('tree_root_size')
assert status['phase']=='complete',status
assert status['frames']>=5 and not status.get('error')
frame_bytes=(folder/'frames.bin').stat().st_size
results['frame_bytes']=frame_bytes
assert frame_bytes==status['frames']*1000000*24
td.cleanup()

out=APP/'validation_1m.json'
out.write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
