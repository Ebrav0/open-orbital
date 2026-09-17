"""Isolated queue integration checks on port 8767; writes queue_validation.json."""
import os,sys,time,json,tempfile,subprocess,urllib.request,urllib.error
from pathlib import Path
APP=Path(__file__).resolve().parents[1];URL='http://127.0.0.1:8767'
def api(path,body=None,method=None):
    req=urllib.request.Request(URL+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'},method=method)
    with urllib.request.urlopen(req,timeout=10) as r:
        raw=r.read();return json.loads(raw) if r.headers.get('Content-Type','').startswith('application/json') else raw
def expect(code,fn):
    try:fn();raise AssertionError(f'Expected HTTP {code}')
    except urllib.error.HTTPError as e:
        assert e.code==code,f'Expected {code}, got {e.code}';return json.load(e).get('error','')
def until(fn,timeout=180):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            value=fn()
            if value:return value
        except (urllib.error.URLError,ConnectionResetError):pass
        time.sleep(.1)
    raise AssertionError('Timed out')
# Queue regression: real small workers, durable order, restart hold, pause barrier,
# cancellation, failure hold, and automatic sequential completion. No production data.
with tempfile.TemporaryDirectory(prefix='orbital-queue-') as td:
    env=dict(os.environ,OBSERVATORY_DATA=td);proc=None
    def start():
        p=subprocess.Popen([sys.executable,str(APP/'server.py'),'--port','8767'],env=env,stdout=subprocess.DEVNULL)
        until(lambda:api('/api/system'));return p
    def phase(j):return api('/api/jobs/'+j['id'])['status']['phase']
    try:
        proc=start()
        a=api('/api/queue/jobs',dict(mode='galaxy',n=10000,threads=1,duration=2,lifecycle_enabled=False,notes='first'))
        b=api('/api/queue/jobs',dict(mode='planets',duration=1,notes='second'))
        c=api('/api/queue/jobs',dict(mode='planets',duration=1,notes='third'))
        assert all(phase(j)=='queued' for j in (a,b,c))
        api('/api/queue',dict(action='up',id=c['id']))
        order=[a['id'],c['id'],b['id']];assert api('/api/queue')['ids']==order
        proc.terminate();proc.wait(timeout=20);proc=start()
        assert api('/api/queue')['ids']==order and not api('/api/queue')['enabled']
        api('/api/queue',dict(action='start'))
        until(lambda:phase(a)=='running')
        api('/api/jobs/'+a['id']+'/control',dict(action='pause'))
        until(lambda:phase(a)=='paused');time.sleep(.5)
        assert phase(b)==phase(c)=='queued'
        api('/api/queue',dict(action='hold'))
        api('/api/jobs/'+a['id']+'/control',dict(action='run'))
        until(lambda:phase(a)=='complete');time.sleep(.5);assert phase(c)=='queued'
        api('/api/queue',dict(action='start'))
        until(lambda:phase(b)=='complete');until(lambda:not api('/api/queue')['enabled'])
        # Save evidence from final file mtimes: the second worker finished before the third began.
        cm=(Path(td)/c['id']/'status.json').stat().st_mtime
        bm=(Path(td)/b['id']/'meta.json').stat().st_mtime
        assert cm<=bm and api('/api/queue')['ids']==[]
        d=api('/api/queue/jobs',dict(mode='planets',duration=1))
        api('/api/jobs/'+d['id'],method='DELETE');assert d['id'] not in api('/api/queue')['ids']
        e=api('/api/queue/jobs',dict(mode='planets',duration=1))
        f=api('/api/queue/jobs',dict(mode='planets',duration=1))
        # Corrupt only an isolated test input to exercise worker failure handling.
        path=Path(td)/e['id']/'config.json';cfg=json.loads(path.read_text());cfg['planet_mass_scale']=['invalid-test-mass'];path.write_text(json.dumps(cfg))
        api('/api/queue',dict(action='start'));until(lambda:phase(e)=='error')
        until(lambda:not api('/api/queue')['enabled']);assert phase(f)=='queued'
        api('/api/queue',dict(action='start'));until(lambda:phase(f)=='complete')
        g=api('/api/queue/jobs',dict(mode='planets',duration=1,notes='resume-a'))
        h=api('/api/queue/jobs',dict(mode='planets',duration=1,notes='resume-b'))
        api('/api/queue',dict(action='start'))
        until(lambda:api('/api/jobs/'+g['id'])['status']['frames']>=1 or phase(g)=='complete')
        proc.terminate();proc.wait(timeout=20);proc=start()
        assert api('/api/queue')['enabled'] is True
        until(lambda:phase(g)=='complete')
        until(lambda:phase(h)=='complete')
        result=dict(order_persisted=True,reordered=True,restart_held=True,pause_blocks_next=True,hold_allows_current_to_finish=True,sequential_completion=True,queued_removal=True,error_holds_queue=True,explicit_continue_after_error=True,restart_keeps_enabled=True)
        (APP/'queue_validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=20)
