# AGENT MAP: this process alone owns a simulation and its frame stream.
# Publish frame bytes before status; checkpoint JSON is the commit pointer (rebound binary + baryon npz).
# Pause stops computation, not viewer playback. Resume may replay uncommitted frames.
# Lifecycle runs after every leapfrog step when enabled. Wall-time cap is 120 h per resume window.
# SIGTERM checkpoints: control.json pause stays paused; otherwise interrupted. worker.pid is for adopt-on-restart.
import json,os,sys,time,math,traceback,signal,shutil
from pathlib import Path
import numpy as np
from physics import galaxy,planets,arrays,diagnostics,set_threads,rebound,GALAXY_DEFAULTS,apply_tree_box
import stellar

WALL_CAP_SECONDS=120*3600

def atomic(path,data):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,allow_nan=False));tmp.replace(path)

def static_types(meta):
    """Type column for runs without lifecycle arrays: disk=MS, halo=HALO, optional SMBH."""
    n=meta['n'];t=np.full(n,stellar.HALO,np.float32)
    if meta['mode']=='planets':t[:]=stellar.MS;return t
    gals=meta.get('galaxies')
    if gals:
        for g in gals:
            a=int(g['start']);t[a:a+int(g['disk_count'])]=stellar.MS
            if g.get('smbh_count'):t[a+int(g['n'])-1]=stellar.SMBH
        return t
    t[:meta['disk_count']]=stellar.MS
    n_smbh=int(meta.get('smbh_count') or 0)
    if n_smbh:t[-n_smbh:]=stellar.SMBH
    return t

def frame_bytes(s,meta,baryons,types_cache):
    q,m=arrays(s)
    if not np.all(np.isfinite(q)):raise RuntimeError('Non-finite particle state; run halted.')
    speed=np.linalg.norm(q[:,3:],axis=1)
    if meta.get('bytes_per_particle',16)==24:
        t=baryons['type'].astype(np.float32) if baryons is not None else types_cache
        frame=np.column_stack((q[:,:3],speed,m,t)).astype('<f4')
    else:frame=np.column_stack((q[:,:3],speed)).astype('<f4')
    return frame.tobytes()

def run(folder):
    folder=Path(folder);config=json.loads((folder/'config.json').read_text());set_threads(config.get('threads',1))
    status=dict(phase='initializing',frames=0,progress=0,wall_seconds=0)
    stopping=[False]
    pid_path=folder/'worker.pid'
    pid_path.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM,lambda *_:stopping.__setitem__(0,True))
    baryons=None
    resumed=False
    try:
        if (folder/'checkpoint.json').exists():
            resumed=True
            ck=json.loads((folder/'checkpoint.json').read_text());s=rebound.Simulation(str(folder/ck.get('file','checkpoint.bin')));meta=json.loads((folder/'meta.json').read_text());initial=ck['initial'];index=ck['index'];status=ck['status'];status['phase']='running'
            if ck.get('baryons'):baryons=stellar.load_baryons(folder/ck['baryons'])
            elif meta.get('lifecycle_enabled'):raise RuntimeError('Checkpoint is missing its stellar lifecycle arrays.')
            with (folder/'frames.bin').open('r+b') as f:f.truncate((index+1)*meta['n']*meta.get('bytes_per_particle',16))
        else:
            atomic(folder/'status.json',status)
            n_build=int(config.get('n') or 0)
            if config.get('mode')=='galaxy' and n_build>=200000:
                status['events']=[f'Building {n_build:,} particles. Tree gravity starts after initial conditions; this can take a few minutes at 1,000,000.']
                atomic(folder/'status.json',status)
            here=Path(__file__).parent
            shutil.copy2(here/'physics.py',folder/'model_source.py');shutil.copy2(here/'stellar.py',folder/'stellar_source.py')
            if config['mode']=='galaxy':s,meta,baryons=galaxy(**{k:v for k,v in config.items() if k in GALAXY_DEFAULTS})
            else:s,meta,baryons=planets(config.get('jupiter_mass',1),config.get('planet_mass_scale'),config.get('perturber_mass',0),config.get('perturber_a',2.5))
            gix=meta.pop('_galaxy_index',None)
            if config['mode']=='galaxy':
                total_steps=round(config['duration']/s.dt);stride=math.ceil(total_steps/240)
                times=[min(i*stride,total_steps)*s.dt for i in range(math.ceil(total_steps/stride)+1)]
            else:times=np.linspace(0,config['duration'],2401).tolist()
            meta.update(id=folder.name,threads=config.get('threads',1),times=times,total_frames=len(times),duration=config['duration'],notes=config.get('notes',''),created=config.get('created'))
            initial=diagnostics(s,meta,baryons);index=0
            meta['initial_diagnostics']=initial;atomic(folder/'meta.json',meta)
            if gix is not None:(folder/'galaxy_index.bin').write_bytes(np.asarray(gix,np.uint8).tobytes())
            (folder/'frames.bin').write_bytes(frame_bytes(s,meta,baryons,static_types(meta)))
            status.update(frames=1,phase='running',computed_time=0,diagnostics=initial,events=(status.get('events') or [])+['Initial conditions created.'],flags={})
        types_cache=static_types(meta) if baryons is None else None
        params=meta.get('params',{});lifecycle=bool(meta.get('lifecycle_enabled')) and baryons is not None
        status.setdefault('flags',{});status.setdefault('events',[])
        def checkpoint():
            filename=f'checkpoint-{index:06d}.bin'
            s.save_to_file(str(folder/'checkpoint.tmp.bin'),delete_file=True)
            (folder/'checkpoint.tmp.bin').replace(folder/filename)
            pointer=dict(file=filename,index=index,initial=initial,status=status)
            if baryons is not None:
                bname=f'baryons-{index:06d}.npz';stellar.save_baryons(folder/'baryons.tmp.npz',baryons);(folder/'baryons.tmp.npz').replace(folder/bname);pointer['baryons']=bname
            atomic(folder/'checkpoint.json',pointer)
            for pattern in ('checkpoint-*.bin','baryons-*.npz'):
                older=sorted(folder.glob(pattern))
                for old in older[:-2]:old.unlink()
        def note(text):
            status['events'].append(text);status['events']=status['events'][-40:]
        def append_history():
            d=status.get('diagnostics') or {};lc=d.get('lifecycle') or {}
            rec=dict(frame=status.get('frames'),t=status.get('computed_time'),wall_seconds=status.get('wall_seconds'),
                     disk_half_radius=d.get('disk_half_radius'),halo_half_radius=d.get('halo_half_radius'),
                     angular_change=d.get('angular_change'),energy_change=d.get('energy_change'),
                     sfr=lc.get('sfr'),births=lc.get('births_cumulative'),deaths=lc.get('deaths_cumulative'),
                     supernovae=lc.get('supernovae_cumulative'),counts=lc.get('counts'))
            with (folder/'diagnostics.jsonl').open('a') as hf:hf.write(json.dumps(rec)+'\n')
        def requested_action():
            try:return json.loads((folder/'control.json').read_text()).get('action')
            except Exception:return 'run'
        def stop_now():
            status['chunk_started_at']=None;checkpoint()
            status['phase']='paused' if requested_action()=='pause' else 'interrupted'
            atomic(folder/'status.json',status)
        checkpoint();atomic(folder/'status.json',status)
        if not resumed:append_history()
        started=time.monotonic();prior_wall=status.get('wall_seconds',0);paused_time=0;last_checkpoint=time.monotonic()
        cap_at=status.get('wall_cap_at',WALL_CAP_SECONDS)
        n_chunks=max(1,len(meta['times'])-1)
        status['estimated_chunk_seconds']=float(config.get('estimated_seconds') or 0)/n_chunks
        def enter_pause():
            nonlocal paused_time
            status['phase']='pausing';status['chunk_started_at']=None;atomic(folder/'status.json',status)
            checkpoint();status['phase']='paused';atomic(folder/'status.json',status)
            p=time.monotonic()
            while requested_action()=='pause' and not stopping[0]:time.sleep(.2)
            paused_time+=time.monotonic()-p
            if stopping[0]:return True
            status['phase']='running';atomic(folder/'status.json',status);return False
        def advance_galaxy(target):
            k=round((target-s.t)/s.dt);next_check=0.0
            while k>0:
                if stopping[0]:return 'stop'
                now=time.monotonic()
                if now>=next_check:
                    if requested_action()=='pause':return 'pause'
                    next_check=now+.25
                try:
                    s.steps(1)
                except RuntimeError as e:
                    if 'outside of simulation box' not in str(e).lower():raise
                    apply_tree_box(s,margin=8.0)
                    s.steps(1)
                if lifecycle:stellar.step(s,baryons,params,s.dt,meta.get('seed',0))
                k-=1
            return 'ok'
        with (folder/'frames.bin').open('ab') as f:
            while index+1<len(meta['times']):
                if stopping[0]:
                    stop_now();return
                if requested_action()=='pause':
                    if enter_pause():stop_now();return
                    continue
                target=meta['times'][index+1];tick=time.monotonic()
                status['chunk_started_at']=time.time();status['phase']='running';atomic(folder/'status.json',status)
                if config['mode']=='galaxy':
                    apply_tree_box(s)
                    outcome=advance_galaxy(target)
                    if outcome=='stop':stop_now();return
                    if outcome=='pause' or requested_action()=='pause':continue
                else:s.integrate(target)
                integration=time.monotonic()-tick;status['chunk_started_at']=None
                f.write(frame_bytes(s,meta,baryons,types_cache));f.flush();index+=1
                status.update(phase='running',frames=index+1,progress=index/(len(meta['times'])-1),computed_time=float(s.t),wall_seconds=prior_wall+time.monotonic()-started-paused_time,last_frame_compute_seconds=integration,steps=int(s.steps_done))
                if index==len(meta['times'])-1 or (config['mode']=='galaxy' and index%40==0):
                    d=diagnostics(s,meta,baryons);d['energy_change']=abs((d['energy']-initial['energy'])/initial['energy']);d['angular_change']=float(np.linalg.norm(np.array(d['angular_momentum'])-initial['angular_momentum'])/max(np.linalg.norm(initial['angular_momentum']),1e-12));d['energy_change_uncertainty']=float(np.hypot(d.get('energy_sigma',0),initial.get('energy_sigma',0))/abs(initial['energy']));d['disk_radius_change']=d['disk_half_radius']/initial['disk_half_radius']-1
                    enc=d.get('encounter')
                    if enc and enc.get('min_separation') is not None:
                        prev=(status.get('diagnostics') or {}).get('encounter') or (initial.get('encounter') or {})
                        old=prev.get('min_separation');now=enc['min_separation']
                        if old is not None and now<old:
                            if now<old*.99:note(f'Closest approach so far: {now*meta.get("length_scale",3):.1f} kpc at {s.t*meta["time_scale"]:.0f} Myr.')
                            enc['min_separation']=now;enc['min_separation_time']=float(s.t)
                        elif old is not None:
                            enc['min_separation']=old;enc['min_separation_time']=prev.get('min_separation_time',float(s.t))
                        sep12=enc.get('separation_12')
                        if sep12 is not None and not status['flags'].get('overlap_12'):
                            gp=meta.get('params') or {}
                            rd_a=float(gp.get('disk_scale',1.2));rd_b=rd_a*float(gp.get('g2_size_ratio',1))
                            if sep12<2*(rd_a+rd_b):
                                status['flags']['overlap_12']=True;note('Galaxies 1 and 2 overlapping (separation < 2 × (Rd_A + Rd_B)).')
                    status['diagnostics']=d
                    lc=d.get('lifecycle')
                    if lc:
                        if lc['supernovae_cumulative']>0 and not status['flags'].get('first_sn'):status['flags']['first_sn']=True;note(f'First supernova at {s.t*meta["time_scale"]:.0f} Myr.')
                        if lc['gas_mass']<=0 and not status['flags'].get('gas_gone'):status['flags']['gas_gone']=True;note(f'Gas reservoir exhausted at {s.t*meta["time_scale"]:.0f} Myr; star formation stops.')
                if config['mode']=='galaxy' or index%20==0 or index==len(meta['times'])-1:atomic(folder/'status.json',status)
                append_history()
                if time.monotonic()-last_checkpoint>15:checkpoint();last_checkpoint=time.monotonic()
                if status['wall_seconds']>=cap_at:
                    status['phase']='interrupted';status['wall_cap_at']=status['wall_seconds']+WALL_CAP_SECONDS;status['wall_capped']=True
                    note('Stopped at the 120-hour compute cap. Resume grants another 120-hour window from this checkpoint.')
                    checkpoint();atomic(folder/'status.json',status);return
        status['phase']='complete';status['progress']=1;note('Run complete. All saved frames are available for replay.');checkpoint();atomic(folder/'status.json',status)
    except Exception as e:
        status.update(phase='error',error=str(e));atomic(folder/'status.json',status);traceback.print_exc()
    finally:
        try:pid_path.unlink()
        except FileNotFoundError:pass
if __name__=='__main__':run(sys.argv[1])
