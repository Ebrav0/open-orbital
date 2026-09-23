"""Measured Linux galaxy workload; writes only under work/linux-benchmarks."""
import argparse,json,os,platform,resource,subprocess,sys,time
from pathlib import Path
import numpy as np
APP=Path(__file__).resolve().parents[1]
OUT=Path(__file__).resolve().parents[3]/'work/linux-benchmarks'
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(APP))
from physics import galaxy,arrays,set_threads,rebound,MODEL_REVISION
p=argparse.ArgumentParser();p.add_argument('--n',type=int,required=True);p.add_argument('--threads',type=int,required=True);p.add_argument('--steps',type=int,required=True);a=p.parse_args()
used=set_threads(a.threads)
start=time.perf_counter();cpu_start=time.process_time();sim,meta,baryons=galaxy(n=a.n,n_galaxies=2,lifecycle_enabled=False);setup=time.perf_counter()-start;setup_cpu=time.process_time()-cpu_start
start=time.perf_counter();sim.steps(1);cold=time.perf_counter()-start
start=time.perf_counter();cpu_start=time.process_time();sim.steps(a.steps);elapsed=time.perf_counter()-start;cpu=time.process_time()-cpu_start
q,m=arrays(sim)
result=dict(timestamp=time.strftime('%Y-%m-%dT%H:%M:%S%z'),host=platform.node(),cpu=platform.processor() or platform.machine(),commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=APP,text=True).strip(),model_revision=MODEL_REVISION,rebound_version=rebound.__version__,rebound_library=str(rebound.clibrebound._name),n=a.n,n_galaxies=2,threads_requested=a.threads,threads_used=used,setup_seconds=setup,setup_cpu_seconds=setup_cpu,cold_step_seconds=cold,timed_steps=a.steps,timed_seconds=elapsed,seconds_per_step=elapsed/a.steps,cpu_wall_ratio=cpu/elapsed,peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1048576 if sys.platform=='darwin' else 1024),finite=bool(np.isfinite(q).all() and np.isfinite(m).all()),simulation_steps=sim.steps_done)
out=OUT/f'galaxy_n{a.n}_t{a.threads}_{time.time_ns()}.json';out.open('x').write(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
