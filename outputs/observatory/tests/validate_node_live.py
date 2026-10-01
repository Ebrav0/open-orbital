"""Live hand-off check against a real node from work/nodes.json on an isolated server (port 8767, temporary data).
Usage: work/venv/bin/python outputs/observatory/tests/validate_node_live.py [node_id]
Runs a 1-thread 10k reference here, a remote planetary run, and splits Mac->node and node->Mac at 30%.
Across CPU architectures frames match up to the hand-off frame and then diverge slowly (floating-point + chaos);
on the same architecture they match exactly. Writes node_live_<id>.json unless OBSERVATORY_TEST_REPORT is set.
Removes every test run (and its node copy) and the node's test folder afterwards."""
import os,sys,json,time,tempfile,subprocess,urllib.request,urllib.error
import numpy as np
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];APP=ROOT/'outputs/observatory';PY=str(ROOT/'work/venv/bin/python');URL='http://127.0.0.1:8767'
def api(path,body=None,method=None):
    req=urllib.request.Request(URL+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'},method=method)
    try:
        with urllib.request.urlopen(req,timeout=120) as r:return json.loads(r.read())
    except urllib.error.HTTPError as e:raise RuntimeError(json.load(e).get('error'))
def wait(jid,timeout=900):
    end=time.time()+timeout
    while time.time()<end:
        j=api(f'/api/jobs/{jid}');s=j['status'];t=(j['location'].get('transfer') or {}).get('state')
        if s['phase']=='error':raise RuntimeError(s.get('error'))
        if t=='failed':raise RuntimeError(j['location']['transfer'].get('error'))
        if s['phase']=='complete' and not s.get('frames_behind') and t in (None,'done'):return j
        time.sleep(1)
    raise RuntimeError('timeout '+jid)
G=dict(mode='galaxy',n=10000,n_galaxies=2,threads=1,duration=3,dt=.02,seed=5,lifecycle_enabled=True)
td=Path(tempfile.mkdtemp(prefix='orbital-xarch-'));(td/'data').mkdir()
NODE=sys.argv[1] if len(sys.argv)>1 else 'computenode1'
node=next(n for n in json.loads((ROOT/'work/nodes.json').read_text())['nodes'] if n['id']==NODE);node['runs']='work/remote-runs-test'
(td/'nodes.json').write_text(json.dumps(dict(nodes=[node])))
env=dict(os.environ,OBSERVATORY_DATA=str(td/'data'),OBSERVATORY_NODES=str(td/'nodes.json'),PYTHONPATH=str(ROOT/'work/openmp'))
proc=subprocess.Popen([PY,str(APP/'server.py'),'--port','8767'],env=env,stdout=subprocess.DEVNULL,stderr=open(td/'err','wb'))
out={'node':NODE,'measured_at':time.strftime('%Y-%m-%dT%H:%M:%S%z')}
try:
    time.sleep(2);print('probe',api(f'/api/nodes/{NODE}/probe',{}).get('ready'),flush=True)
    t0=time.time();ref=api('/api/jobs',dict(G,node='local'));r=wait(ref['id']);out['reference_wall']=round(time.time()-t0,1)
    fs=r['meta']['n']*24;refb=np.fromfile(td/'data'/ref['id']/'frames.bin',dtype='<f4').reshape(-1,10000,6)
    t0=time.time();pl=api('/api/jobs',dict(mode='planets',duration=12,node=NODE));pj=wait(pl['id']);out['remote_planets']=dict(wall=round(time.time()-t0,1),frames=pj['status']['frames'],energy_change=pj['status']['diagnostics']['energy_change'])
    for name,start,to,at in (('mac_to_node','local',NODE,.3),('node_to_mac',NODE,'local',.3)):
        t0=time.time();a=api('/api/jobs',dict(G,node=start,split=dict(at=at,to=to)));j=wait(a['id'],1800)
        b=np.fromfile(td/'data'/a['id']/'frames.bin',dtype='<f4').reshape(-1,10000,6);h=j['location']['history'];k=h[1]['start_frame']
        pos=np.abs(b[:,:,:3]-refb[:,:,:3]).max(axis=(1,2))
        out[name]=dict(wall=round(time.time()-t0,1),segments=[x['node'] for x in h],handoff_frame=k,frames=len(b),finite=bool(np.isfinite(b).all()),
            identical_before_handoff=bool((b[:k+1]==refb[:k+1]).all()),max_pos_diff_first_after=float(pos[k+1]),max_pos_diff_final=float(pos[-1]),
            types_identical_final=bool((b[-1,:,5]==refb[-1,:,5]).all()),mass_sum_final=float(b[-1,:,4].sum()),ref_mass_sum_final=float(refb[-1,:,4].sum()),
            transfer_seconds=j['location']['transfer'].get('seconds'))
        print(name,json.dumps(out[name]),flush=True)
    for jid in [x['id'] for x in api('/api/jobs?view=summary')]:api(f'/api/jobs/{jid}',method='DELETE')
    out['cleanup']='all test runs removed (node copies too)'
    subprocess.run(['ssh','-o','BatchMode=yes',node['host'],'rm -rf ~/open-orbital/work/remote-runs-test'],timeout=60)
finally:
    proc.terminate();proc.wait(20)
    Path(os.environ.get('OBSERVATORY_TEST_REPORT',APP/f'node_live_{NODE}.json')).write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
    if not out.get('cleanup'):print((td/'err').read_text()[-3000:])
