"""Isolated compute-node checks on port 8767 with a fake `ssh` that runs the remote shell locally under a temp $HOME.
Covers: probe, remote-only run with frame sync, per-node concurrency, planned split local→node and node→local,
manual hand-off of a running job, a three-machine chain, twin runs and their divergence endpoint, standby pick-up
while the Mac is "asleep" (server and Mac worker frozen with SIGSTOP) followed by return to the Mac, byte-identical
frames versus unsplit 1-thread references, remote removal, and a clear error for a node without key access.
Writes nodes_validation.json unless OBSERVATORY_TEST_REPORT is set."""
import os,sys,time,json,signal,tempfile,subprocess,urllib.request,urllib.error,hashlib
from pathlib import Path
APP=Path(__file__).resolve().parents[1];ROOT=APP.parents[1];URL='http://127.0.0.1:8767'
PY=str(ROOT/'work/venv/bin/python');OPENMP=str(ROOT/'work/openmp')
FAKE_SSH='''#!/bin/sh
# Test double: drop ssh options and the host, run the remote command here with the node's own HOME.
while [ $# -gt 0 ]; do case "$1" in -o) shift 2;; -*) shift;; *) host=$1; shift; break;; esac; done
case "$host" in *dead*) echo "$host: Permission denied (publickey,password)." >&2; exit 255;; esac
exec env HOME="$FAKE_NODE_HOME" sh -c "$*"
'''
def api(path,body=None,method=None):
    req=urllib.request.Request(URL+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'},method=method)
    try:
        with urllib.request.urlopen(req,timeout=60) as r:return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if method or body is not None:e.msg=f"{e.msg}: {json.loads(e.read() or b'{}').get('error')}"
        raise
def expect(code,fn):
    try:fn();raise AssertionError(f'Expected HTTP {code}')
    except urllib.error.HTTPError as e:
        assert e.code==code,f'Expected {code}, got {e.code}';return e.msg.split(': ',1)[-1]
def until(fn,timeout=300,what='condition'):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            v=fn()
            if v:return v
        except (urllib.error.URLError,ConnectionResetError):pass
        time.sleep(.25)
    raise AssertionError('Timed out waiting for '+what)
def done(jid):
    j=api(f'/api/jobs/{jid}')
    if j['status']['phase']=='error':raise AssertionError(f"{jid} error: {j['status'].get('error')}")
    return j if j['status']['phase']=='complete' and not j['status'].get('frames_behind') and (j['location'].get('transfer') or {}).get('state') in (None,'done') else None
GALAXY=dict(mode='galaxy',n=10000,n_galaxies=2,threads=1,duration=3,dt=.02,seed=5,lifecycle_enabled=True)
LONG=dict(GALAXY,duration=9)
GRACE=6
with tempfile.TemporaryDirectory(prefix='orbital-nodes-') as td:
    td=Path(td);data=td/'data';data.mkdir();home=td/'nodehome';home.mkdir();fb=td/'bin';fb.mkdir()
    (fb/'ssh').write_text(FAKE_SSH);(fb/'ssh').chmod(0o755)
    (td/'nodes.json').write_text(json.dumps(dict(nodes=[
        dict(id='fakenode',label='Fake node',host='tester@fake',root='~/oo',python=PY,pythonpath=OPENMP,runs='work/remote-runs',always_on=True),
        dict(id='fakenode2',label='Fake node 2',host='tester@fake2',root='~/oo2',python=PY,pythonpath=OPENMP,runs='work/remote-runs',always_on=True),
        dict(id='deadnode',label='Dead node',host='tester@dead',root='~/oo',python=PY,pythonpath=OPENMP,runs='work/remote-runs',always_on=True)])))
    env=dict(os.environ,OBSERVATORY_DATA=str(data),OBSERVATORY_NODES=str(td/'nodes.json'),FAKE_NODE_HOME=str(home),PATH=f'{fb}:{os.environ["PATH"]}',PYTHONPATH=OPENMP,
             OBSERVATORY_HEARTBEAT_SECONDS='1',OBSERVATORY_STANDBY_GRACE=str(GRACE),OBSERVATORY_STANDBY_MIN_INTERVAL='2')
    proc=subprocess.Popen([PY,str(APP/'server.py'),'--port','8767'],env=env,stdout=subprocess.DEVNULL,stderr=open(td/'server.err','wb'))
    result={};t0=time.monotonic()
    try:
        until(lambda:api('/api/system'),60,'server')
        h=api('/api/nodes/fakenode/probe',{});assert h['ready'],h;result['probe']=dict(ready=h['ready'],rebound=h.get('rebound'),cores=h.get('cores'))
        assert api('/api/nodes/fakenode2/probe',{})['ready']
        err=expect(400,lambda:api('/api/jobs',dict(GALAXY,node='deadnode')));assert 'ssh-copy-id' in err,err;result['dead_node_error']=err
        # Reference on this Mac and a remote-only planetary run at the same time: one active job per node.
        ref=api('/api/jobs',dict(GALAXY,node='local'))
        planets=api('/api/jobs',dict(mode='planets',duration=12,node='fakenode'))
        ref_long=api('/api/jobs',dict(LONG,node='fakenode2'))   # reference for the standby test (same CPU, 1 thread)
        result['concurrent_nodes']=True
        pj=until(lambda:done(planets['id']),300,'remote planets')
        rdir=home/'oo/work/remote-runs/jobs'/planets['id']
        local_frames=(data/planets['id']/'frames.bin').read_bytes();remote_frames=(rdir/'frames.bin').read_bytes()
        assert local_frames==remote_frames and pj['status']['frames']==pj['meta']['total_frames'],'planet frames not mirrored'
        result['remote_planets']=dict(frames=pj['status']['frames'],energy_change=pj['status']['diagnostics'].get('energy_change'),mirrored_bytes=len(local_frames))
        rj=until(lambda:done(ref['id']),600,'reference');refb=(data/ref['id']/'frames.bin').read_bytes()
        result['reference']=dict(id=ref['id'],frames=rj['status']['frames'],wall_seconds=rj['status'].get('wall_seconds'),sha256=hashlib.sha256(refb).hexdigest()[:16])
        fs=rj['meta']['n']*rj['meta']['bytes_per_particle']
        def check(jid,label,ref=None):
            ref=refb if ref is None else ref
            try:j=until(lambda:done(jid),600,label)
            except AssertionError:
                j=api(f'/api/jobs/{jid}');result[label]=dict(status={k:j['status'].get(k) for k in ('phase','frames','error','frames_behind')},location=j['location']);raise
            b=(data/jid/'frames.bin').read_bytes()
            zero=[i for i in range(len(b)//fs) if not any(b[i*fs:i*fs+fs])]
            segs=[s['node'] for s in j['location']['history']]
            result[label]=dict(id=jid,segments=segs,frames=j['status']['frames'],identical_to_reference=b==ref,zero_frames=zero,transfer=j['location'].get('transfer'))
            assert not zero,f'{label}: zero frames {zero}'
            assert b==ref,f'{label}: frames differ from the unsplit reference'
            return j
        # Regression: a remote run that ends between syncs must not keep the node "busy" and block the next hand-off.
        quick=api('/api/jobs',dict(mode='planets',duration=1,node='fakenode'));until(lambda:done(quick['id']),120,'quick remote run')
        a=api('/api/jobs',dict(GALAXY,node='local',split=dict(at=.3,to='fakenode')))
        ja=check(a['id'],'split_local_to_node');assert ja['location']['history'][-1]['node']=='fakenode' and len(ja['location']['history'])==2
        b=api('/api/jobs',dict(GALAXY,node='fakenode',split=dict(at=.4,to='local')))
        jb=check(b['id'],'split_node_to_local');assert [s['node'] for s in jb['location']['history']]==['fakenode','local']
        c=api('/api/jobs',dict(GALAXY,node='fakenode'))
        until(lambda:api(f"/api/jobs/{c['id']}")['status'].get('frames',0)>=20,300,'remote frames before manual move')
        api(f"/api/jobs/{c['id']}/move",{'node':'local'})
        jc=check(c['id'],'manual_move_node_to_local');assert [s['node'] for s in jc['location']['history']]==['fakenode','local']
        # B: a chain across three machines.
        d=api('/api/jobs',dict(GALAXY,node='local',legs=[dict(node='local',until=.3),dict(node='fakenode',until=.6),dict(node='fakenode2')]))
        jd=check(d['id'],'chain_three_machines');assert [s['node'] for s in jd['location']['history']]==['local','fakenode','fakenode2']
        # C: twin runs on two machines at once, then their divergence (same CPU and 1 thread: exactly zero).
        e=api('/api/jobs',dict(GALAXY,node='local',twin='fakenode'));twin_id=e['location']['twin']
        check(e['id'],'twin_a');check(twin_id,'twin_b')
        cmp=api(f"/api/jobs/{e['id']}/twin");assert len(cmp['points'])==rj['status']['frames'] and max(pt['max'] for pt in cmp['points'])==0.0,cmp['points'][-1]
        result['twin_compare']=dict(points=len(cmp['points']),max_divergence=max(pt['max'] for pt in cmp['points']),sample=cmp['sample'],nodes=[cmp['a']['node'],cmp['b']['node']])
        # A: the Mac "sleeps" mid-run; the standby node picks the run up, then hands it back when the Mac wakes.
        lj=until(lambda:done(ref_long['id']),600,'long reference');refl=(data/ref_long['id']/'frames.bin').read_bytes()
        sb=api('/api/jobs',dict(LONG,node='local',standby='fakenode',return_on_wake=True));sid=sb['id']
        until(lambda:((api(f'/api/jobs/{sid}')['location'].get('standby') or {}).get('index') or 0)>0,300,'shadow checkpoint after frame 0')
        wpid=int((data/sid/'worker.pid').read_text());frozen_at=api(f'/api/jobs/{sid}')['status']['frames']
        os.kill(proc.pid,signal.SIGSTOP);os.kill(wpid,signal.SIGSTOP)
        sbfile=home/'oo/work/remote-runs/jobs'/sid/'standby.json'
        try:
            end=time.monotonic()+GRACE+30
            while time.monotonic()<end and not json.loads(sbfile.read_text()).get('taken'):time.sleep(.5)
            picked=json.loads(sbfile.read_text());assert picked.get('taken'),'node did not pick the run up'
            time.sleep(3)
        finally:
            os.kill(wpid,signal.SIGCONT);os.kill(proc.pid,signal.SIGCONT)
        js=check(sid,'standby_pickup',ref=refl);segs=[s['node'] for s in js['location']['history']]
        assert segs[:2]==['local','fakenode'] and js['location']['history'][1].get('reason')=='standby pick-up',segs
        result['standby_pickup'].update(frozen_at_frame=frozen_at,picked_up_at_index=picked.get('index'),heartbeat_age=picked.get('heartbeat_age'),note=js['location']['standby'].get('note'),returned_to_mac=segs[-1]=='local')
        rdir_b=home/'oo/work/remote-runs/jobs'/planets['id']
        api(f"/api/jobs/{planets['id']}",method='DELETE');assert not rdir_b.exists(),'remote folder left behind';result['remote_removed']=True
        result['elapsed_seconds']=round(time.monotonic()-t0,1);result['ok']=True
    finally:
        proc.terminate()
        try:proc.wait(20)
        except subprocess.TimeoutExpired:proc.kill()
        out=Path(os.environ.get('OBSERVATORY_TEST_REPORT',APP/'nodes_validation.json'));out.write_text(json.dumps(result,indent=2,default=str))
        print(json.dumps(result,indent=2,default=str))
        if not result.get('ok'):print((td/'server.err').read_text()[-3000:])
