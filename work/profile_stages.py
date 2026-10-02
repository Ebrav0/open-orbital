import os,subprocess,json
from pathlib import Path
root=Path.cwd();f=root/'work/observatory-data/67be855d5342';ck=json.loads((f/'checkpoint.json').read_text())
code='''import sys,time,resource,json
sys.path.insert(0,'outputs/observatory')
from physics import rebound
import stellar
from pathlib import Path
f=Path(sys.argv[1]);ck=json.loads((f/'checkpoint.json').read_text());meta=json.loads((f/'meta.json').read_text());s=rebound.Simulation(str(f/ck['file']));b=stellar.load_baryons(f/ck['baryons'])
def cpu():
 r=resource.getrusage(resource.RUSAGE_SELF);return r.ru_utime+r.ru_stime
s.steps(1);gravity=life=0.;a=time.perf_counter();c=cpu()
for _ in range(8):
 t=time.perf_counter();s.steps(1);gravity+=time.perf_counter()-t
 t=time.perf_counter();stellar.step(s,b,meta['params'],s.dt,meta['seed']);life+=time.perf_counter()-t
w=time.perf_counter()-a
print(json.dumps(dict(wall=w,cpu_percent=(cpu()-c)/w*100,gravity=gravity,lifecycle=life)))
'''
results=[]
for bind in ['false','close','false','close']:
 env=dict(os.environ,PYTHONPATH=str(root/'work/openmp'),OMP_NUM_THREADS='14',OMP_DYNAMIC='false',OMP_WAIT_POLICY='PASSIVE',OMP_PROC_BIND=bind,OMP_PLACES='cores')
 r=subprocess.run([str(root/'work/venv/bin/python'),'-c',code,str(f)],env=env,capture_output=True,text=True,check=True)
 d=json.loads(r.stdout);d['binding']=bind;results.append(d);print(d,flush=True)
(root/'outputs/observatory/thread_stages.json').write_text(json.dumps(results,indent=2))
