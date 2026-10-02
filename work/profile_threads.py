import os,sys,json,time,subprocess,urllib.request
from pathlib import Path
root=Path.cwd();base='http://127.0.0.1:8766';jid='67be855d5342';folder=root/'work/observatory-data'/jid
req=urllib.request.Request(base+'/api/jobs/'+jid+'/control',data=b'{"action":"pause"}',headers={'Content-Type':'application/json'})
json.load(urllib.request.urlopen(req))
for _ in range(300):
 j=json.load(urllib.request.urlopen(base+'/api/jobs/'+jid))
 if j['status']['phase']=='paused':break
 time.sleep(.2)
else:raise RuntimeError('Pause timeout')
ck=json.loads((folder/'checkpoint.json').read_text());checkpoint=folder/ck['file']
code='''import sys,time,resource,json
import rebound
s=rebound.Simulation(sys.argv[1]);s.steps(1)
a=time.perf_counter();r=resource.getrusage(resource.RUSAGE_SELF);c=r.ru_utime+r.ru_stime
s.steps(6)
r=resource.getrusage(resource.RUSAGE_SELF);w=time.perf_counter()-a
print(json.dumps(dict(wall=w,cpu_percent=(r.ru_utime+r.ru_stime-c)/w*100)))
'''
results=[]
for n,bind in [(10,'close'),(14,'close'),(14,'false')]:
 env=dict(os.environ,PYTHONPATH=str(root/'work/openmp'),OMP_NUM_THREADS=str(n),OMP_DYNAMIC='false',OMP_WAIT_POLICY='PASSIVE',OMP_PROC_BIND=bind,OMP_PLACES='cores')
 r=subprocess.run([str(root/'work/venv/bin/python'),'-c',code,str(checkpoint)],env=env,capture_output=True,text=True,check=True)
 d=json.loads(r.stdout);d.update(threads=n,binding=bind);results.append(d);print(d,flush=True)
(root/'outputs/observatory/thread_profile.json').write_text(json.dumps(dict(checkpoint=str(checkpoint),steps=6,includes_lifecycle=False,results=results),indent=2))
