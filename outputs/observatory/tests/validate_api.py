"""Isolated end-to-end API test for model revision 4 on port 8767 with a temp data dir.
Covers: encounter validation, 256-per-galaxy helper via SCHEMA, pause, restart + checkpoint recovery,
24-byte frames, summary view, /lab page, log tail, preview, and DELETE rules.
Writes api_validation_r4.json (never api_validation.json or api_validation_r3.json)."""
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
with tempfile.TemporaryDirectory(prefix='orbital-api-') as td:
    env=os.environ.copy();env['OBSERVATORY_DATA']=td;proc=None;result={}
    def start():
        p=subprocess.Popen([sys.executable,str(APP/'server.py'),'--port','8767'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        until(lambda:api('/api/system'));return p
    try:
        proc=start()
        lab=urllib.request.urlopen(URL+'/lab').read().decode();assert '<canvas' not in lab and 'three' not in lab.lower() and 'Start computation' in lab and 'Stop computation' in lab and 'lab.js' in lab and 'id="start-compute"' in lab and 'id="stop-compute"' in lab
        assert 'three.module.js' in urllib.request.urlopen(URL+'/').read().decode()
        for js in('/lab.js','/shared.js'):
            src=urllib.request.urlopen(URL+js).read().decode();assert "from 'three'" not in src and 'three.module' not in src and 'WebGLRenderer' not in src and '/frames' not in src,js
        result['bad_knob_error']=expect(400,lambda:api('/api/jobs',dict(mode='galaxy',n=10000,warmth=9)))
        result['over_budget_error']=expect(400,lambda:api('/api/jobs',dict(mode='galaxy',n=200000,threads=1,duration=5000)));assert '120' in result['over_budget_error']
        expect(400,lambda:api('/api/jobs',dict(mode='galaxy',n=12345)));expect(400,lambda:api('/api/jobs',dict(mode='planets',duration=80)))
        result['n_galaxies_6_error']=expect(400,lambda:api('/api/jobs',dict(mode='galaxy',n=10000,n_galaxies=6)))
        # Five galaxies at N=10k is allowed (256×5=1280). Pause and remove so the recovery test has a free slot.
        five=api('/api/jobs',dict(mode='galaxy',n=10000,threads=4,duration=1,n_galaxies=5,lifecycle_enabled=False,notes='five-galaxy floor check'))
        until(lambda:(q:=api(f'/api/jobs/{five["id"]}'))['meta'].get('n_galaxies')==5 and q)
        assert five['config']['n_galaxies']==5
        api(f'/api/jobs/{five["id"]}/control',dict(action='pause'));until(lambda:api(f'/api/jobs/{five["id"]}')['status']['phase']=='paused')
        assert api(f'/api/jobs/{five["id"]}',method='DELETE')['removed']==five['id']
        result['five_galaxy_10000_ok']=True
        cfg=dict(mode='galaxy',n=10000,threads=4,duration=4,seed=99,n_galaxies=2,disk_mass=1.2,halo_mass=18,disk_fraction=.3,disk_scale=1.1,disk_thickness=.08,halo_scale=4,warmth=.9,smbh_mass=.005,lifecycle_enabled=True,gas_fraction=.4,t_sf=.6,lifecycle_speed=40,sf_density_bias=.7,imf_mmin=.08,imf_mmax=100,grow_rate=.2,sn_kick_kms=20,theta=.4,softening=.06,dt=.02,notes='api test')
        j=api('/api/jobs',cfg);jid=j['id'];url=f'/api/jobs/{jid}';assert j['config']['smbh_mass']==.005 and j['config']['notes']=='api test' and j['config']['estimated_seconds']>0 and j['config']['n_galaxies']==2
        until(lambda:(q:=api(url))['status']['frames']>2 and q)
        assert expect(400,lambda:api('/api/jobs',dict(mode='planets')))
        expect(400,lambda:api(url,method='DELETE'))
        pause_reply=api(url+'/control',dict(action='pause'))
        assert pause_reply.get('ok') and (pause_reply['status']['phase'] in ('paused','pausing') or pause_reply['status'].get('pause_pending'))
        paused=until(lambda:(q:=api(url))['status']['phase']=='paused' and q)
        assert not paused['status'].get('pause_pending')
        count=paused['status']['frames'];time.sleep(.4);assert api(url)['status']['frames']==count
        meta=paused['meta'];assert meta['bytes_per_particle']==24 and meta['frame_layout']=='xyzsmt' and meta['model_revision']==4 and meta['n_galaxies']==2 and len(meta['galaxies'])==2 and meta['smbh_count']==2 and meta['lifecycle_enabled']
        first=api(url+'/frames?start=0');assert len(first)==10000*24
        import numpy as np;f0=np.frombuffer(first,'<f4').reshape(-1,6);assert set(np.unique(f0[:,5]).tolist())<= {0.,1.,2.,3.,4.,5.,6.,7.,8.} and abs(f0[:,4].sum()-(1.2+18+.005)*2)<1e-3
        summary=api('/api/jobs?view=summary');me=[x for x in summary if x['id']==jid][0];assert 'times' not in me['meta'] and 'initial_diagnostics' not in me['meta'] and 'params' not in me['meta'] and 'galaxies' in me['meta'] and 'protected' in me and me['protected'] is False
        result['summary_bytes_per_job']=len(json.dumps(me));assert result['summary_bytes_per_job']<8000
        assert 'times' in api(url)['meta']
        ck=json.loads((Path(td)/jid/'checkpoint.json').read_text());assert ck.get('baryons','').startswith('baryons-') and (Path(td)/jid/ck['baryons']).exists()
        proc.terminate();proc.wait(timeout=20);proc=start()
        assert api(url)['status']['phase']=='interrupted'
        api(url+'/control',dict(action='run'));end=until(lambda:(q:=api(url))['status']['phase']=='complete' and q)
        assert end['status']['frames']==end['meta']['total_frames'] and api(url+'/frames?start=0')==first and end['status']['computed_time']>3.99
        lc=end['status']['diagnostics']['lifecycle'];assert lc['births_cumulative']>0 and abs(lc['baryon_mass']-2.4)<1e-6
        result.update(pause_frame=count,recovered_frames=end['status']['frames'],recovered_time=end['status']['computed_time'],lifecycle=dict(births=lc['births_cumulative'],deaths=lc['deaths_cumulative'],supernovae=lc['supernovae_cumulative'],counts=lc['counts']))
        expect(400,lambda:api(url+'/frames?start=99999'))
        log=api(url+'/log?tail=10');assert isinstance(log['lines'],list)
        pv=api('/api/preview',dict(mode='galaxy',n=100000,warmth=.6,n_galaxies=2));assert len(pv)==8000*24
        iso=api('/api/jobs',dict(mode='galaxy',n=10000,threads=4,duration=1,n_galaxies=1,lifecycle_enabled=False,notes='isolated r4'))
        iurl=f'/api/jobs/{iso["id"]}';ij=until(lambda:(q:=api(iurl))['status']['frames']>=1 and q['meta'].get('n_galaxies')==1 and q)
        assert ij['meta']['model_revision']==4 and ij['meta']['bytes_per_particle']==24 and len(api(iurl+'/frames?start=0'))==10000*24
        api(iurl+'/control',dict(action='pause'));until(lambda:api(iurl)['status']['phase']=='paused');assert api(iurl,method='DELETE')['removed']==iso['id']
        result['isolated_n_galaxies_1_ok']=True
        pj=api('/api/jobs',dict(mode='planets',duration=2,planet_mass_scale=[1,1,1,1,3,1,1,1],perturber_mass=.002,perturber_a=3));pid=pj['id'];purl=f'/api/jobs/{pid}'
        pend=until(lambda:(q:=api(purl))['status']['phase']=='complete' and q);assert pend['meta']['n']==10 and len(api(purl+'/frames?start=0'))==10*24
        result['planets_energy_change']=pend['status']['diagnostics']['energy_change'];assert result['planets_energy_change']<1e-9
        assert 'preserved' in expect(400,lambda:api('/api/jobs/44c528079f88',method='DELETE')).lower()
        expect(404,lambda:api('/api/jobs/abcdefabcdef',method='DELETE'))
        assert api(purl,method='DELETE')['removed']==pid and not (Path(td)/pid).exists();expect(404,lambda:api(purl))
        assert len(api('/api/jobs?view=summary'))==1
        result.update(initial_frame_preserved=True,concurrent_job_rejected=True,invalid_frame_rejected=True,running_delete_rejected=True,protected_delete_rejected=True,finished_delete_ok=True,lab_page_has_no_three=True,bytes_per_particle=24,model_revision=4)
        (APP/'api_validation_r4.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    finally:
        if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=20)
