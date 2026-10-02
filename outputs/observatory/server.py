# AGENT MAP: HTTP handlers supervise workers; they do not integrate physics. nodes.py runs workers on SSH compute nodes.
# Keep loopback binding, input bounds, one-active-job-per-node checks, protected runs and existing run data.
# SCHEMA here is the validation authority; static/shared.js mirrors it for the Compute page.
"""Loopback-only server and isolated CPU job manager. Stdlib HTTP, local assets."""
import os,sys,json,re,time,subprocess,threading,uuid,argparse,signal,shutil,math,struct,platform
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs,unquote
from worker import atomic
from physics import effective_threads,performance_cores
import physics
import nodes
BASE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('OBSERVATORY_DATA',BASE.parents[1]/'work/observatory-data')).resolve();DATA.mkdir(parents=True,exist_ok=True)
PROCESSES={};LOCK=threading.Lock()
PROTECTED={'0e45a855ba11','44c528079f88','ff56d195ce89','58ab7c268cdd'}
WALL_CAP_HOURS=120;MAX_RUNS=24;ACTIVE=['running','initializing','pausing']
REFERENCE_SECONDS=157.84   # measured: 100,000 particles, 10 threads, 500 steps, model revision 2

def cpu_label():
    try:
        for line in Path('/proc/cpuinfo').read_text().splitlines():
            if line.startswith('model name'):
                return line.split(':',1)[1].strip()
    except OSError:pass
    if sys.platform=='darwin':
        try:
            r=subprocess.run(['sysctl','-n','machdep.cpu.brand_string'],capture_output=True,text=True,timeout=1)
            if r.returncode==0 and r.stdout.strip():return r.stdout.strip()
        except (OSError,subprocess.SubprocessError):pass
    return platform.processor() or platform.machine()

CLONE_AZIMUTH={2:0,3:120,4:240,5:180}
# id -> (kind, allowed) where kind is 'choice', 'float', 'int', 'bool', 'list8'
SCHEMA=dict(
    n=('choice',[10000,30000,100000,200000,500000,1000000]),threads=('choice',[1,4,8,10,14]),seed=('int',(0,2**32-1)),
    n_galaxies=('choice',[1,2,3,4,5]),
    disk_mass=('float',(.2,5)),halo_mass=('float',(2,80)),disk_fraction=('float',(.15,.45)),disk_scale=('float',(.5,3)),disk_thickness=('float',(.03,.25)),halo_scale=('float',(1.5,10)),warmth=('float',(.4,3)),smbh_mass=('float',(0,.1)),
    lifecycle_enabled=('bool',None),realistic=('bool',None),gas_fraction=('float',(0,.8)),t_sf=('float',(.1,20)),lifecycle_speed=('float',(1,80)),sf_density_bias=('float',(0,1)),imf_mmin=('float',(.05,1)),imf_mmax=('float',(20,150)),grow_rate=('float',(0,1)),sn_kick_kms=('float',(0,200)),
    theta=('float',(.25,.7)),softening=('float',(.03,.15)),dt=('float',(.01,.04)),
    jupiter_mass=('choice',[1,3,10]),planet_mass_scale=('list8',(.25,10)),perturber_mass=('float',(0,.01)),perturber_a=('float',(.5,40)))
for _i in range(2,6):
    SCHEMA[f'g{_i}_mass_ratio']=('float',(.1,3));SCHEMA[f'g{_i}_size_ratio']=('float',(.3,2))
    SCHEMA[f'g{_i}_sep']=('float',(8,80));SCHEMA[f'g{_i}_impact']=('float',(0,20));SCHEMA[f'g{_i}_vrel']=('float',(.4,4))
    SCHEMA[f'g{_i}_azimuth']=('float',(0,360));SCHEMA[f'g{_i}_inclination']=('float',(0,180));SCHEMA[f'g{_i}_disk_tilt']=('float',(0,180))
    SCHEMA[f'g{_i}_spin']=('choice',[1,-1])
_CLONE_KEYS=[k for i in range(2,6) for k in (f'g{i}_mass_ratio',f'g{i}_size_ratio',f'g{i}_sep',f'g{i}_impact',f'g{i}_vrel',f'g{i}_azimuth',f'g{i}_inclination',f'g{i}_disk_tilt',f'g{i}_spin')]
GALAXY_KEYS=['n','threads','seed','n_galaxies']+_CLONE_KEYS+['disk_mass','halo_mass','disk_fraction','disk_scale','disk_thickness','halo_scale','warmth','smbh_mass','lifecycle_enabled','gas_fraction','t_sf','lifecycle_speed','sf_density_bias','imf_mmin','imf_mmax','grow_rate','sn_kick_kms','theta','softening','dt','realistic']
PLANET_KEYS=['seed','jupiter_mass','planet_mass_scale','perturber_mass','perturber_a']
DEFAULTS=dict(n=100000,threads=8,seed=731,n_galaxies=2,disk_mass=1,halo_mass=20,disk_fraction=.3,disk_scale=1.2,disk_thickness=.08,halo_scale=4,warmth=1,smbh_mass=0,lifecycle_enabled=True,gas_fraction=.2,t_sf=2,lifecycle_speed=1,sf_density_bias=.7,imf_mmin=.08,imf_mmax=100,grow_rate=.2,sn_kick_kms=0,theta=.4,softening=.06,dt=.02,realistic=False,jupiter_mass=1,planet_mass_scale=[1]*8,perturber_mass=0,perturber_a=2.5)
for _i in range(2,6):
    DEFAULTS[f'g{_i}_mass_ratio']=1;DEFAULTS[f'g{_i}_size_ratio']=1;DEFAULTS[f'g{_i}_sep']=20;DEFAULTS[f'g{_i}_impact']=4;DEFAULTS[f'g{_i}_vrel']=2
    DEFAULTS[f'g{_i}_azimuth']=CLONE_AZIMUTH[_i];DEFAULTS[f'g{_i}_inclination']=0;DEFAULTS[f'g{_i}_disk_tilt']=0;DEFAULTS[f'g{_i}_spin']=1

class NotFound(ValueError):pass

def folder(jid):
    if not re.fullmatch(r'[a-f0-9]{12}',jid):raise ValueError('Invalid experiment ID')
    p=DATA/jid
    if not p.is_dir():raise NotFound('Experiment not found')
    return p

def read(p,default):
    try:return json.loads(p.read_text())
    except FileNotFoundError:return default

def alive(jid):
    proc=PROCESSES.get(jid)
    if proc is not None and proc.poll() is None:return True
    p=DATA/jid
    if p.is_dir() and nodes.is_remote(p):
        r=nodes.remote_alive(jid)
        # Unreachable node: keep the last synced phase instead of declaring the worker dead.
        return read(p/'status.json',{}).get('phase') in ACTIVE if r is None else r
    return False

def annotate_pause(status,cfg,meta,control):
    """If control.json asks for pause before the worker has stopped, expose remaining wait from the current leapfrog step."""
    status=dict(status)
    if control.get('action')!='pause' or status.get('phase') in ('paused','complete','error','interrupted'):
        return status
    status['pause_pending']=True
    last=status.get('last_frame_compute_seconds')
    est=status.get('estimated_chunk_seconds')
    frames=max(1,(meta.get('total_frames') or 241)-1)
    if est is None and cfg.get('estimated_seconds'):
        est=cfg['estimated_seconds']/frames
    chunk=last if last else est
    if status.get('phase') in ('initializing','queued','pausing') or chunk is None:
        status['pause_eta_seconds']=None
        return status
    duration=float(cfg.get('duration') or 1);dt=float(cfg.get('dt') or .02)
    steps_per_chunk=max(1,round(duration/dt/frames)) if cfg.get('mode')=='galaxy' else 1
    status['pause_eta_seconds']=max(0.25,float(chunk)/steps_per_chunk)
    return status

def job(p,summary=False):
    cfg=read(p/'config.json',{});status=read(p/'status.json',dict(phase='queued',frames=0,progress=0));meta=read(p/'meta.json',{})
    control=read(p/'control.json',{});loc=nodes.location(p);remote=loc.get('node','local')!='local'
    ck=p/'.hub'/'checkpoint.json' if remote else p/'checkpoint.json'
    if status['phase'] in ['running','initializing','pausing'] and not alive(p.name):
        if ck.exists():
            status['phase']='paused' if control.get('action')=='pause' else 'interrupted'
            status['error']='Worker stopped. Resume the saved checkpoint.' if status['phase']=='interrupted' else status.get('error')
            if status['phase']=='paused' and 'error' in status:status.pop('error',None)
        else:
            status['phase']='error';status['error']='Worker stopped before its first checkpoint.'
    status=annotate_pause(status,cfg,meta,control)
    if ck.exists():
        try:status['checkpoint_age_seconds']=time.time()-ck.stat().st_mtime
        except OSError:pass
    if summary:
        meta={k:v for k,v in meta.items() if k not in ('times','bodies','initial_diagnostics','params')}
        status={k:v for k,v in status.items() if k!='flags'}
        if 'events' in status:status['events']=status['events'][-20:]
    r=nodes.REMOTE.get(p.name) or {}
    loc=dict(loc,plan=nodes.plan_of(loc),sync=dict(reachable=r.get('reachable'),age=time.time()-r['synced_at'] if r.get('synced_at') else None,error=r.get('error'),alive=r.get('alive')) if remote else None)
    return dict(id=p.name,config=cfg,status=status,meta=meta,protected=p.name in PROTECTED,location=loc)

def jobs(summary=False):return sorted([job(p,summary) for p in DATA.iterdir() if p.is_dir() and (p/'config.json').exists()],key=lambda x:x['config'].get('created',0),reverse=True)

def busy(except_id=None,node='local'):
    """One active experiment per compute node. A paused worker still in memory, or an incoming hand-off, counts."""
    if node=='local' and any(jid!=except_id and proc is not None and proc.poll() is None for jid,proc in PROCESSES.items()):return True
    for j in jobs(True):
        if j['id']==except_id:continue
        t=j['location'].get('transfer') or {}
        if t.get('state') in ('pausing','copying','starting') and node in (t.get('to'),t.get('source')):return True
        if j['location'].get('node','local')!=node:continue
        if j['status']['phase'] in ACTIVE or alive(j['id']):return True
    return False

def pid_running(pid):
    # Linux keeps an exited process visible until its parent reaps it.
    stat=Path(f'/proc/{pid}/stat')
    if stat.exists():
        try:
            if stat.read_text().split(') ',1)[1][0]=='Z':return False
        except (OSError,IndexError):pass
    try:os.kill(pid,0);return True
    except OSError:return False

def cmdline_of(pid):
    try:
        r=subprocess.run(['ps','-p',str(pid),'-ww','-o','command='],capture_output=True,text=True)
        return r.stdout.strip()
    except Exception:return ''

class Adopted:
    def __init__(self,pid):self.pid=pid
    def poll(self):return None if pid_running(self.pid) else 1
    def terminate(self):
        try:os.kill(self.pid,signal.SIGTERM)
        except OSError:pass
    def kill(self):
        try:os.kill(self.pid,signal.SIGKILL)
        except OSError:pass
    def wait(self,timeout=None):
        end=time.time()+(timeout if timeout is not None else 1e9)
        while time.time()<end:
            if self.poll() is not None:return
            time.sleep(.05)
        raise subprocess.TimeoutExpired(str(self.pid),timeout)

def adopt(p):
    path=p/'worker.pid'
    if not path.exists():return False
    try:pid=int(path.read_text().strip())
    except Exception:return False
    if not pid_running(pid):return False
    cmd=cmdline_of(pid)
    if str(p) not in cmd:return False
    PROCESSES[p.name]=Adopted(pid);return True

def spawn(p):
    if nodes.is_remote(p):
        node=nodes.node_of(p);threads=int(read(p/'config.json',{}).get('threads',1) or 1)
        cores=(nodes.HEALTH.get(node) or {}).get('cores') or threads
        return nodes.spawn_remote(p,min(threads,cores))
    spawn_local(p)

def spawn_local(p):
    if alive(p.name):return
    if adopt(p):return
    requested=int(read(p/'config.json',{}).get('threads',1) or 1)
    env=os.environ.copy()
    env['OMP_NUM_THREADS']=str(effective_threads(requested))
    env['OMP_DYNAMIC']='false'
    env['OMP_WAIT_POLICY']='PASSIVE'
    env['OMP_PROC_BIND']='false'
    env.pop('OMP_PLACES',None)
    cmd=[sys.executable,str(BASE/'worker.py'),str(p)]
    cafe=shutil.which('caffeinate')
    if cafe:cmd=[cafe,'-dims']+cmd
    with (p/'worker.log').open('ab') as log:
        PROCESSES[p.name]=subprocess.Popen(cmd,stdout=log,stderr=log,env=env,start_new_session=True)

def stop_proc(proc):
    if proc is None or proc.poll() is not None:return
    try:
        if not isinstance(proc,Adopted) and getattr(proc,'pid',None):
            os.killpg(proc.pid,signal.SIGTERM)
        else:proc.terminate()
    except OSError:proc.terminate()

def terminate_local(jid,timeout=60):
    proc=PROCESSES.get(jid)
    stop_proc(proc)
    if proc is None:return
    try:proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if not isinstance(proc,Adopted) and getattr(proc,'pid',None):os.killpg(proc.pid,signal.SIGKILL)
            else:proc.kill()
        except OSError:pass
        try:proc.wait(timeout=5)
        except Exception:pass

def active_worker_pid():
    for jid,proc in PROCESSES.items():
        if proc is None or proc.poll() is not None:continue
        path=DATA/jid/'worker.pid'
        if path.exists():
            try:return int(path.read_text().strip())
            except Exception:pass
        return getattr(proc,'pid',None)
    return None

def coerce(key,value):
    kind,allowed=SCHEMA[key]
    if kind=='bool':return bool(value) if not isinstance(value,str) else value.lower() in ('1','true','yes','on')
    if kind=='choice':
        v=float(value)
        if v not in [float(a) for a in allowed]:raise ValueError(f'{key} must be one of {allowed}')
        return int(v) if float(v).is_integer() else v
    if kind=='int':
        v=int(value)
        if not allowed[0]<=v<=allowed[1]:raise ValueError(f'{key} must be between {allowed[0]} and {allowed[1]}')
        return v
    if kind=='float':
        v=float(value)
        if not math.isfinite(v) or not allowed[0]<=v<=allowed[1]:raise ValueError(f'{key} must be between {allowed[0]} and {allowed[1]}')
        return v
    if kind=='list8':
        vals=[float(x) for x in list(value)]
        if len(vals)!=8 or any(not math.isfinite(x) or not allowed[0]<=x<=allowed[1] for x in vals):raise ValueError('planet_mass_scale needs eight values between %s and %s'%allowed)
        return vals
    raise ValueError(key)

def node_estimate(cfg,node_id):
    """Mac estimator × the node's measured speed factor, at the thread count the node can actually run."""
    if node_id=='local':return estimate_seconds(cfg)
    node=nodes.get(node_id);cores=(nodes.HEALTH.get(node_id) or {}).get('cores')
    threads=min(int(cfg.get('threads') or 1),cores) if cores else int(cfg.get('threads') or 1)
    return estimate_seconds(dict(cfg,threads=threads))*float(node.get('speed') or 1)

def placement(config,cfg):
    """Validate the starting machine, an optional chain of legs (split), a twin machine and a standby choice.
    The 120 h cap applies to the whole run: the worker's wall clock travels with the checkpoint across hand-offs."""
    node_id=str(config.get('node') or 'local');nodes.get(node_id)
    legs=config.get('legs')
    if not legs and config.get('split'):   # two-leg form used before multi-leg plans
        sp=config['split'];legs=[dict(node=node_id,until=float(sp.get('at'))),dict(node=str(sp.get('to') or ''))]
    legs=nodes.validate_legs(node_id,legs) if legs else None
    spans=[(l['node'],l['until']-(legs[i-1]['until'] if i else 0.)) for i,l in enumerate(legs)] if legs else [(node_id,1.)]
    est=sum(f*node_estimate(cfg,n) for n,f in spans)
    if est>WALL_CAP_HOURS*3600:raise ValueError(f'Estimated {est/3600:.0f} h on these machines exceeds the {WALL_CAP_HOURS}-hour compute cap. Shorten the span, lower N, or use faster machines.')
    twin=str(config.get('twin') or '') or None
    if twin:
        nodes.get(twin)
        if twin==node_id:raise ValueError('A twin must run on a different machine.')
        if legs:raise ValueError('Twin runs use one machine each; turn off the split.')
        if node_estimate(cfg,twin)>WALL_CAP_HOURS*3600:raise ValueError(f'The twin on {nodes.get(twin)["label"]} would exceed the {WALL_CAP_HOURS}-hour cap.')
    standby=config.get('standby')
    standby=None if standby in (None,'','off') else str(standby)
    if standby and standby!='auto':
        nodes.get(standby)
        if standby=='local':raise ValueError('Standby needs another machine.')
    involved={n for n,_ in spans}|({twin} if twin else set())|({standby} if standby and standby!='auto' else set())
    for nid in involved-{'local'}:
        h=nodes.HEALTH.get(nid) or nodes.probe(nid)
        if not h.get('ready'):raise ValueError(f'{nodes.get(nid)["label"]} is not ready: '+(h.get('error') or h.get('python_error') or 'REBOUND not found on the node.'))
        if h.get('disk_kb') is not None and h['disk_kb']*1024<disk_bytes(cfg)+2*1024**3:raise ValueError(f'{nodes.get(nid)["label"]} lacks disk space for this run.')
    return dict(node=node_id,legs=legs,twin=twin,standby=standby,return_on_wake=bool(config.get('return_on_wake',True)),estimated_seconds=est)

def resolve_standby(choice,node_id,exclude=()):
    """Standby applies to runs that start on this Mac. 'auto' picks the fastest ready always-on node."""
    if node_id!='local' or not choice:return None
    return nodes.default_standby(exclude) if choice=='auto' else choice

_REALISTIC_CACHE={}
def realistic_info(cfg):
    """Revision-6 numerics for a galaxy config (cached): the softening and starting step the run will use, the gas count,
    per-galaxy particle masses and particle-noise heating times, and the thread-independent per-step cost of the SPH
    and lifecycle work (measured on this Mac, see HANDOFF). The standard-physics heating times are included to compare."""
    base={k:cfg[k] for k in GALAXY_KEYS if k in cfg and k in physics.GALAXY_DEFAULTS}
    key=json.dumps({k:v for k,v in base.items() if k not in ('threads','seed','dt','theta','realistic')},sort_keys=True)
    if key in _REALISTIC_CACHE:return _REALISTIC_CACHE[key]
    P=physics.galaxy_params(dict(base,realistic=True));rs=physics.realistic_settings(P);P['softening']=rs['softening']
    S=physics.galaxy_params(dict(base,realistic=False,revision=physics.MODEL_REVISION))
    counts=[int(c) for c in rs['counts']];ts=physics.MYR_PER_TIME
    gals=[]
    for i,(Q,c,hr,hs) in enumerate(zip(physics.galaxy_param_list(P),counts,physics.heating_times(P,counts),physics.heating_times(S,counts))):
        nd=int(c*float(Q['disk_fraction']));nb=1 if float(Q['smbh_mass'])>0 else 0;nh=c-nd-nb;ng=int(round(nd*float(Q['gas_fraction'])))
        gals.append(dict(id=i+1,n=c,disk=nd-ng,gas=ng,halo=nh,disk_particle_msun=float(Q['disk_mass'])/max(nd,1)*1e10,halo_particle_msun=float(Q['halo_mass'])/max(nh,1)*1e10,
            heating_myr=hr*ts,heating_standard_myr=hs*ts))
    n_gas=sum(g['gas'] for g in gals);n=int(cfg['n'])
    out=dict(softening=rs['softening'],softening_rule=rs['softening_rule'],dt_initial=rs['dt_initial'],a_max=rs['a_max'],eta=rs['eta'],galaxies=gals,n_gas=n_gas,
        hydro_seconds_per_step=REALISTIC_STEP_FIXED+REALISTIC_STEP_PER_GAS*n_gas+REALISTIC_STEP_PER_PARTICLE*n,
        heating_myr=min(g['heating_myr'] for g in gals),heating_standard_myr=min(g['heating_standard_myr'] for g in gals))
    if len(_REALISTIC_CACHE)>256:_REALISTIC_CACHE.clear()
    _REALISTIC_CACHE[key]=out;return out

# Per-step cost of revision-6 work outside REBOUND (two SPH evaluations, lifecycle, bookkeeping), single-process numpy.
# Measured 2026-09-30 on this M4 Pro, 8 threads: 30k/1,800 gas 31 ms, 100k/6,000 gas 92 ms, 200k/12,000 gas 191 ms per step. A prediction.
REALISTIC_STEP_FIXED=.002;REALISTIC_STEP_PER_GAS=1.5e-5;REALISTIC_STEP_PER_PARTICLE=8e-8

def estimate_seconds(cfg):
    """Wall-time estimate from the measured revision-2 100k/10-thread reference. Order-of-magnitude for lifecycle, 500k and 1M.
    Revision 6 uses its starting step (close passages shorten it, so real runs can take longer) plus the SPH/lifecycle cost."""
    if cfg['mode']=='planets':
        bodies=10 if cfg.get('perturber_mass',0)>0 else 9
        return .25*cfg['duration']/12*(bodies/9)**2
    if cfg.get('realistic'):
        info=realistic_info(cfg);steps=cfg['duration']/info['dt_initial']
        return estimate_seconds(dict(cfg,realistic=False,dt=info['dt_initial'],lifecycle_enabled=True))+steps*info['hydro_seconds_per_step']
    n=cfg['n'];steps=cfg['duration']/cfg['dt']
    extra=1.05 if int(cfg.get('n_galaxies') or 1)>1 else 1
    threads=effective_threads(cfg['threads'])
    return REFERENCE_SECONDS*(n/1e5)*math.log(n)/math.log(1e5)*(steps/500)*(10/threads)*(1.15 if cfg.get('lifecycle_enabled') else 1)*extra

def max_duration(cfg):
    trial=dict(cfg,duration=1.);per_unit=estimate_seconds(trial)
    return WALL_CAP_HOURS*3600/per_unit if per_unit>0 else float('inf')

def disk_bytes(cfg):
    n=cfg['n'] if cfg['mode']=='galaxy' else 10;frames=241 if cfg['mode']=='galaxy' else 2401
    return int(1.5*n*24*frames+2*n*120)

def normalize(config):
    mode=config.get('mode')
    if mode not in ['galaxy','planets']:raise ValueError('Choose galaxy or planets')
    keys=GALAXY_KEYS if mode=='galaxy' else PLANET_KEYS
    cfg=dict(mode=mode)
    for k in keys:cfg[k]=coerce(k,config.get(k,DEFAULTS[k]))
    duration=float(config.get('duration',10 if mode=='galaxy' else 12))
    if not math.isfinite(duration) or duration<=0:raise ValueError('Duration must be positive')
    if mode=='planets':
        cfg.update(n=10 if cfg['perturber_mass']>0 else 9,threads=1)
        if not 1<=duration<=50:raise ValueError('Planetary span must be between 1 and 50 years')
    elif cfg['n']<256*int(cfg.get('n_galaxies') or 1):
        raise ValueError('Need at least 256 particles per galaxy (raise N or lower galaxy count).')
    cfg['duration']=duration
    if mode=='galaxy' and cfg.get('realistic'):cfg['lifecycle_enabled']=True;cfg['lifecycle_speed']=1.
    est=estimate_seconds(cfg)
    if est>WALL_CAP_HOURS*3600:
        unit='model time units' if mode=='galaxy' else 'years'
        raise ValueError(f'Estimated {est/3600:.0f} h exceeds the {WALL_CAP_HOURS}-hour compute cap. Maximum span for these settings is about {max_duration(cfg):.1f} {unit}.')
    notes=str(config.get('notes',''))[:2000]
    cfg.update(notes=notes,estimated_seconds=est,created=time.time())
    return cfg

# Queue state is a single atomic document. HTTP mutations and dispatch share LOCK.
# A queued job has no worker. Paused/interrupted current queue work blocks dispatch.
# Daemon restart keeps queue.enabled and auto-resumes interrupted jobs whose control is run.
QUEUE_FILE=DATA/'queue.json'
STOP_SCHEDULER=threading.Event()

def recover():
    """Adopt live workers, persist dead ones, resume at most one interrupted run (control=run, not wall-capped)."""
    for p in DATA.iterdir():
        if not p.is_dir() or not (p/'config.json').exists():continue
        loc=nodes.location(p)
        if (loc.get('transfer') or {}).get('state') in ('pausing','copying','starting'):
            loc['transfer'].update(state='failed',error='Server restarted during the hand-off. Check the run, then resume or retry.');nodes.save_location(p,loc)
        if loc.get('node','local')!='local':continue
        if adopt(p):continue
        st=read(p/'status.json',{});ctl=read(p/'control.json',{});phase=st.get('phase')
        if phase in ('complete','error','queued','paused'):continue
        if phase in ('running','initializing','pausing'):
            if (p/'checkpoint.json').exists():
                st['phase']='paused' if ctl.get('action')=='pause' else 'interrupted'
                if st['phase']=='interrupted':st['error']='Worker stopped. Resume the saved checkpoint.'
                else:st.pop('error',None)
            else:
                st.update(phase='error',error='Worker stopped before its first checkpoint.')
            atomic(p/'status.json',st)
    q=queue_state()
    if q.get('current'):
        try:
            cur=job(folder(q['current']),True)
            if cur['status']['phase']=='complete':q['current']=None;save_queue(q)
        except NotFound:
            q['current']=None;save_queue(q)
    if busy():return
    candidates=[]
    for j in jobs(True):
        if j['location'].get('node','local')!='local':continue
        ctl=read(folder(j['id'])/'control.json',{})
        if j['status']['phase']=='interrupted' and ctl.get('action')=='run' and not j['status'].get('wall_capped'):
            candidates.append(j)
    if not candidates:return
    pick=next((c for c in candidates if c['id']==q.get('current')),None) or candidates[0]
    spawn(folder(pick['id']))

def history_points(p,cap=2400):
    path=p/'diagnostics.jsonl'
    if not path.exists():return dict(points=[])
    lines=path.read_text().splitlines()[-cap:];points=[]
    for line in lines:
        try:points.append(json.loads(line))
        except Exception:pass
    return dict(points=points)

# ---------- star inspector: one particle's saved history ----------
# Particle order is fixed for a run's lifetime (lifecycle changes type/mass in place), so row `index` of every saved frame
# is the same body. Galaxy centres are estimates read from saved frames only: the galaxy's central black hole when it has
# one, else a shrinking-sphere density centre of a fixed sample of its disk particles. Cached per run in memory; frames
# after the committed checkpoint are recomputed because a resume can rewrite them.
CENTER_SAMPLE=1024;CENTER_CACHE={}

def galaxy_slices(meta):
    gals=meta.get('galaxies')
    if gals:return gals
    n=int(meta['n']);return [dict(id=1,start=0,n=n,disk_count=int(meta.get('disk_count',n)),smbh_count=int(meta.get('smbh_count') or 0))]

def density_center(pts):
    import numpy as np
    c=np.median(pts,axis=0);keep=pts
    while len(keep)>64:
        r=np.linalg.norm(keep-c,axis=1);keep=keep[r<=np.quantile(r,.7)];c=keep.mean(axis=0)
    return c

def disk_normal(pts,c):
    """Smallest-variance axis of the sampled disk inside its median radius; None when the sample is no longer flat."""
    import numpy as np
    d=pts-c;r=np.linalg.norm(d,axis=1);inner=d[r<=np.median(r)]
    if len(inner)<32:return None
    _,sv,vt=np.linalg.svd(inner-inner.mean(axis=0),full_matrices=False)
    return None if sv[2]>.45*sv[1] else vt[2]

def frame_centers(A,i,gals):
    import numpy as np
    out=[]
    for g in gals:
        a=int(g['start']);dc=int(g.get('disk_count') or g['n'])
        idx=np.unique(np.linspace(a,a+dc-1,min(CENTER_SAMPLE,dc)).astype(np.int64));pts=np.asarray(A[i,idx,:3],np.float64)
        if g.get('smbh_count'):c=np.asarray(A[i,a+int(g['n'])-1,:3],np.float64);method='black hole'
        else:c=density_center(pts);method='density'
        nrm=disk_normal(pts,c);out.append(dict(c=c,normal=nrm,method=method))
    return out

def display_sample(n,every,meta):
    """Particles the viewer draws when thinning a huge run: 0, every, 2·every, … then each central black hole.
    static/viewer.js builds the same list (sampleMap) to translate display indices back to particle indices."""
    import numpy as np
    gals=meta.get('galaxies') or []
    extra=[int(g['start'])+int(g['n'])-1 for g in gals if g.get('smbh_count')] if gals else list(range(n-int(meta.get('smbh_count') or 0),n))
    return np.concatenate([np.arange(0,n,every),np.asarray(extra,dtype=np.int64)]).astype(np.int64)

def track_particle(p,index,start=0):
    import numpy as np
    j=job(p);meta=j['meta'];n=int(meta.get('n') or j['config'].get('n') or 0);frames=int(j['status'].get('frames') or 0)
    stride=int(meta.get('bytes_per_particle') or 16)//4;mode=j['config'].get('mode')
    if not n:raise ValueError('This run has no particles yet')
    if index<0 or index>=n:raise ValueError('Particle index out of range')
    if frames>20000:raise ValueError('Track too long')
    start=max(0,min(int(start),frames));times=meta.get('times') or []
    info=dict(id=j['id'],index=index,n=n,mode=mode,frames=frames,start=start,
              units=dict(length=meta.get('length_unit'),length_scale=meta.get('length_scale',1),time=meta.get('time_unit'),time_scale=meta.get('time_scale',1),
                         velocity_kms=meta.get('velocity_unit_kms',4.7406 if mode=='planets' else None),mass_solar=meta.get('mass_unit_solar',1)))
    if mode=='planets':
        bodies=meta.get('bodies') or [];info.update(name=bodies[index]['name'] if index<len(bodies) else f'Body {index}',component='body',galaxy=None,center_method='sun',galaxies=0)
    else:
        gals=galaxy_slices(meta);g=next((g for g in gals if g['start']<=index<g['start']+g['n']),gals[0]);k=index-int(g['start'])
        comp='central black hole' if g.get('smbh_count') and k==int(g['n'])-1 else 'disk' if k<int(g.get('disk_count') or 0) else 'halo'
        info.update(galaxy=int(g.get('id',1)),component=comp,galaxies=len(gals),center_method='black hole' if all(x.get('smbh_count') for x in gals) else 'density')
    path=p/'frames.bin'
    if not path.exists() or not frames or start>=frames:return dict(info,points=[])
    A=np.memmap(path,dtype='<f4',mode='r',shape=(frames,n,stride))
    rows=np.asarray(A[start:frames,index,:],np.float64)
    if mode=='planets':
        suns=np.asarray(A[start:frames,0,:3],np.float64)
    else:
        ck=read(p/'checkpoint.json',{});final=int(ck['index']) if 'index' in ck else frames-3
        cache=CENTER_CACHE.setdefault(j['id'],{})
        for i in [i for i in cache if i>final or i>=frames]:del cache[i]
        for i in range(start,frames):
            if i not in cache:cache[i]=frame_centers(A,i,gals)
    del A
    points=[]
    for off,row in enumerate(rows):
        i=start+off;pos=row[:3]
        rec=dict(frame=i,t=times[i] if i<len(times) else None,x=float(pos[0]),y=float(pos[1]),z=float(pos[2]))
        if stride>3:rec['speed']=float(row[3])
        if stride>4:rec['mass']=float(row[4])
        if stride>5:rec['type']=int(round(row[5]))
        if mode=='planets':
            d=pos-suns[off];rec['r']=float(np.linalg.norm(d));rec['height']=float(d[2])
        else:
            cs=cache[i];own=cs[info['galaxy']-1];d=pos-own['c'];rec['r']=float(np.linalg.norm(d))
            rec['height']=None if own['normal'] is None else float(abs(d@own['normal']))
            dist=[float(np.linalg.norm(pos-c['c'])) for c in cs];rec['nearest']=int(np.argmin(dist))+1
            if len(cs)>1:rec['nearest_r']=min(dist)
        points.append(rec)
    return dict(info,points=points)

def twin_compare(p):
    """Divergence between twin runs frame by frame: median / 90th-percentile / max particle separation over a strided
    sample of up to ~20,000 particles, plus diagnostics side by side. Cached per frame counts in twin_compare.json."""
    import numpy as np
    other=nodes.location(p).get('twin')
    if not other:raise NotFound('This run has no twin')
    q=folder(other);a,b=job(p),job(q)
    n=int(a['meta'].get('n') or 0);stride=int(a['meta'].get('bytes_per_particle') or 16)//4
    frames=min(int(a['status'].get('frames') or 0),int(b['status'].get('frames') or 0))
    key=[frames,a['status'].get('frames'),b['status'].get('frames')];cache=read(p/'twin_compare.json',{})
    if cache.get('key')==key:return cache
    points=[]
    if n and frames and n==int(b['meta'].get('n') or 0):
        A=np.memmap(p/'frames.bin',dtype='<f4',mode='r',shape=(frames,n,stride));B=np.memmap(q/'frames.bin',dtype='<f4',mode='r',shape=(frames,n,stride))
        idx=np.arange(0,n,max(1,n//20000));times=a['meta'].get('times') or []
        for i in range(frames):
            d=np.linalg.norm(A[i,idx,:3].astype(np.float64)-B[i,idx,:3],axis=1)
            points.append(dict(frame=i,t=times[i] if i<len(times) else None,median=float(np.median(d)),p90=float(np.percentile(d,90)),max=float(d.max())))
        del A,B
    da,db=a['status'].get('diagnostics') or {},b['status'].get('diagnostics') or {}
    def pick(d):
        enc=d.get('encounter') or {};lc=d.get('lifecycle') or {}
        return dict(disk_half_radius=d.get('disk_half_radius'),energy_change=d.get('energy_change'),angular_change=d.get('angular_change'),
                    min_separation=enc.get('min_separation'),min_separation_time=enc.get('min_separation_time'),births=lc.get('births_cumulative'),supernovae=lc.get('supernovae_cumulative'))
    out=dict(key=key,a=dict(id=a['id'],node=a['location'].get('node'),frames=a['status'].get('frames'),**pick(da)),b=dict(id=b['id'],node=b['location'].get('node'),frames=b['status'].get('frames'),**pick(db)),
             points=points,sample=int(len(range(0,n,max(1,n//20000)))) if n else 0,time_scale=a['meta'].get('time_scale'),length_scale_kpc=3.0)
    try:atomic(p/'twin_compare.json',out)
    except OSError:pass
    return out

def queue_state():
    return read(QUEUE_FILE,dict(enabled=False,ids=[],current=None,message='Ready to arrange experiments.'))

def save_queue(q):atomic(QUEUE_FILE,q)

def check_space(cfg,queued=()):
    need=disk_bytes(cfg)+sum(disk_bytes(read(folder(jid)/'config.json',{})) for jid in queued)+2*1024**3
    if shutil.disk_usage(DATA).free<need:raise ValueError(f'At least {need/1024**3:.1f} GiB of free disk space is required for these experiments.')

def queue_nodes(q):
    ids=list(q['ids'])+([q['current']] if q.get('current') else [])
    return {nodes.node_of(DATA/jid) for jid in ids if (DATA/jid).is_dir()}

def create(config,enqueue=False):
    cfg=normalize(config);q=queue_state();place=placement(config,cfg);twin=place['twin']
    machines=[place['node']]+([twin] if twin else [])
    if twin and enqueue:raise ValueError('Start twin runs directly; the queue runs experiments one at a time.')
    for node in machines:
        if not enqueue and busy(node=node):raise ValueError(f'{nodes.get(node)["label"]} is already computing. Pause that experiment or choose another machine.')
        if not enqueue and q['enabled'] and node in queue_nodes(q):raise ValueError(f'The queue is using {nodes.get(node)["label"]}. Hold the queue or choose another machine.')
    if len(jobs(True))+len(machines)>MAX_RUNS:raise ValueError(f'{MAX_RUNS} experiments are saved. Remove a run before creating more.')
    check_space(dict(cfg,n=cfg['n']*len(machines)) if cfg['mode']=='galaxy' else cfg,q['ids'])
    ids=[uuid.uuid4().hex[:12] for _ in machines];made=[]
    for i,(jid,node) in enumerate(zip(ids,machines)):
        c=dict(cfg,placement=dict(place,node=node,legs=place['legs'] if i==0 else None,estimated_seconds=place['estimated_seconds'] if i==0 else node_estimate(cfg,node)))
        if twin:c['twin_of' if i else 'twin']=ids[1-i]
        p=DATA/jid;p.mkdir();atomic(p/'config.json',c);atomic(p/'control.json',dict(action='run'))
        sb=resolve_standby(place['standby'],node,exclude=machines)
        nodes.save_location(p,dict(node=node,plan=dict(legs=place['legs'],leg=0) if place['legs'] and i==0 else None,transfer=None,twin=ids[1-i] if twin else None,
            standby=dict(node=sb,return_on_wake=place['return_on_wake']) if sb else None,
            history=[dict(node=node,started_at=time.time(),start_frame=0,ended_at=None)]))
        atomic(p/'status.json',dict(phase='queued' if enqueue else 'initializing',frames=0,progress=0));made.append(p)
    if enqueue:
        q['ids'].append(ids[0]);save_queue(q)
    else:
        for p in made:
            try:spawn(p)
            except nodes.NodeError as e:
                atomic(p/'status.json',dict(phase='error',frames=0,progress=0,error=str(e)));raise ValueError(str(e))
    return job(made[0])

def dispatch_queue():
    """Called under LOCK. Never overlap workers, including a completing worker's final I/O."""
    q=queue_state()
    if not q['enabled']:return
    if q.get('current'):
        current=job(folder(q['current']),True)
        if alive(current['id']):return
        if current['status']['phase']!='complete':
            q.update(enabled=False,message='Queue held: review the stopped experiment before continuing.');save_queue(q);return
        q['current']=None;save_queue(q)
    # Older paused experiments are independent saved work, not queue barriers.
    # A live worker — including a paused one still in its wait loop — blocks dispatch on the same node only.
    head_node=nodes.node_of(DATA/q['ids'][0]) if q['ids'] else 'local'
    for j in jobs(True):
        if j['location'].get('node','local')!=head_node:continue
        if j['status']['phase'] in ACTIVE:
            q['current']=j['id'];save_queue(q);return
        if alive(j['id']):return
    if not q['ids']:
        q.update(enabled=False,message='Queue finished.');save_queue(q);return
    jid=q['ids'][0];p=folder(jid)
    try:check_space(read(p/'config.json',{}),q['ids'][1:])
    except ValueError as e:
        q.update(enabled=False,message=str(e));save_queue(q);return
    # Commit the active slot before launch. A crash here recovers as interrupted/error,
    # with the remaining order intact and automatic dispatch disabled on restart.
    q['ids'].pop(0);q.update(current=jid,message='Running experiments in order.');save_queue(q)
    atomic(p/'status.json',dict(phase='initializing',frames=0,progress=0))
    try:spawn(p)
    except (OSError,nodes.NodeError) as e:
        atomic(p/'status.json',dict(phase='error',frames=0,progress=0,error=str(e)))
        q.update(enabled=False,message='Could not launch worker.');save_queue(q)

def queue_action(data):
    q=queue_state();action=data.get('action')
    if action=='start':
        if q.get('current'):
            j=job(folder(q['current']),True)
            if j['status']['phase'] in ('complete','error'):q['current']=None
        q.update(enabled=True,message='Queue enabled. A paused queue run must be resumed or removed before the next starts.')
    elif action=='hold':q.update(enabled=False,message='Queue held. The current experiment may finish; no next run will start.')
    elif action in ('up','down'):
        jid=data.get('id')
        if jid not in q['ids']:raise ValueError('Only waiting experiments can be reordered.')
        i=q['ids'].index(jid);n=i+(-1 if action=='up' else 1)
        if not 0<=n<len(q['ids']):raise ValueError('Experiment is already at that end of the queue.')
        q['ids'][i],q['ids'][n]=q['ids'][n],q['ids'][i]
    else:raise ValueError('Unsupported queue action')
    save_queue(q);return q

def scheduler():
    while not STOP_SCHEDULER.wait(.25):
        with LOCK:
            try:dispatch_queue()
            except Exception as e:
                q=queue_state();q.update(enabled=False,message=f'Queue held: {e}');save_queue(q)

def remove(jid):
    if jid in PROTECTED:raise ValueError('This experiment is a preserved comparison run and cannot be removed.')
    p=folder(jid);j=job(p,True);phase=j['status']['phase']
    if phase in ACTIVE:raise ValueError('Pause or finish this experiment before removing it.')
    if (j['location'].get('transfer') or {}).get('state') in ('pausing','copying','starting'):raise ValueError('Wait for the hand-off to finish before removing this experiment.')
    armed_on=(j['location'].get('standby') or {}).get('armed_on')
    if armed_on and not nodes.is_remote(p):
        try:nodes.disarm(p,armed_on,remove=True)
        except nodes.NodeError as e:raise ValueError(f'{e}. Could not remove the standby copy; try again when the node is reachable.')
    if nodes.is_remote(p):
        try:nodes.remove_remote(p)
        except nodes.NodeError as e:
            if phase=='paused':raise ValueError(f'{e}. The paused remote worker could not be stopped; try again when the node is reachable.')
    proc=PROCESSES.pop(jid,None)
    stop_proc(proc)
    if proc is not None:
        try:proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            try:
                if not isinstance(proc,Adopted) and getattr(proc,'pid',None):os.killpg(proc.pid,signal.SIGKILL)
                else:proc.kill()
            except OSError:pass
            try:proc.wait(timeout=5)
            except Exception:pass
    q=queue_state()
    if jid in q['ids']:q['ids'].remove(jid)
    if q.get('current')==jid:q['current']=None
    save_queue(q)
    shutil.rmtree(p);CENTER_CACHE.pop(jid,None)
    return dict(ok=True,removed=jid)

def preview(config):
    """Initial conditions only, 8,000 particles, in a subprocess with a timeout. Returns one xyzsmt frame."""
    cfg=normalize(dict(config,n=10000,threads=1,duration=1));cfg['n']=8000
    code='import sys,json,numpy as np;from physics import galaxy,planets,arrays,MODEL_REVISION;import stellar\ncfg=json.load(sys.stdin)\n' \
         's,meta,b=galaxy(**{"revision":MODEL_REVISION,**{k:v for k,v in cfg.items() if k in %r}}) if cfg["mode"]=="galaxy" else planets(cfg.get("jupiter_mass",1),cfg.get("planet_mass_scale"),cfg.get("perturber_mass",0),cfg.get("perturber_a",2.5))\n' \
         'q,m=arrays(s)\n' \
         'if b is not None: t=b["type"]\n' \
         'else:\n' \
         ' t=np.full(s.N,7,np.float32);gals=meta.get("galaxies") or []\n' \
         ' if gals:\n' \
         '  for gal in gals:\n' \
         '   t[gal["start"]:gal["start"]+gal["disk_count"]]=2\n' \
         '   if gal.get("smbh_count"): t[gal["start"]+gal["n"]-1]=8\n' \
         ' else: t[:meta.get("disk_count",s.N)]=2\n' \
         't=t.astype(np.float32)\n' \
         'sys.stdout.buffer.write(np.column_stack((q[:,:3],np.linalg.norm(q[:,3:],axis=1),m,t)).astype("<f4").tobytes())'%GALAXY_KEYS
    r=subprocess.run([sys.executable,'-c',code],input=json.dumps(cfg).encode(),capture_output=True,timeout=12,cwd=BASE,env=dict(os.environ,OMP_NUM_THREADS='1'))
    if r.returncode!=0:raise ValueError('Preview failed: '+r.stderr.decode(errors='replace')[-300:])
    return r.stdout

def log_tail(p,tail):
    path=p/'.hub'/'.hub-log' if nodes.is_remote(p) else p/'worker.log'
    if not path.exists():return []
    with path.open('rb') as f:
        f.seek(0,2);size=f.tell();f.seek(max(0,size-32*1024));data=f.read()
    return data.decode(errors='replace').splitlines()[-tail:]

def _safe(fn,*a):
    try:return fn(*a)
    except Exception:return None

def node_list():
    out=[dict(nodes.get('local'),cores=os.cpu_count(),performance_cores=performance_cores(),health=dict(reachable=True,ready=True,cores=os.cpu_count()),
              busy=busy(node='local'))]
    for n in nodes.registry():
        out.append(dict(n,kind='ssh',health=nodes.HEALTH.get(n['id']),benchmark=nodes.BENCH.get(n['id']),busy=busy(node=n['id'])))
    return dict(nodes=out,engine_hash=nodes.engine_hash())

def configure_nodes():
    nodes.HOOKS.update(atomic=atomic,spawn_local=spawn_local,stop_local=terminate_local,busy=lambda node,except_id=None:busy(except_id,node),
        alive_local=lambda jid:PROCESSES.get(jid) is not None and PROCESSES[jid].poll() is None,reference_seconds=REFERENCE_SECONDS)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):pass
    def send(self,data,status=200,mime='application/json'):
        if mime=='application/json':data=json.dumps(data,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store' if mime=='application/json' else 'no-cache');self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass
    def same_origin(self):
        origin=self.headers.get('Origin');host=self.headers.get('Host')
        return not origin or origin==f'http://{host}'
    def do_GET(self):
        try:
            u=urlparse(self.path);parts=u.path.strip('/').split('/');qs=parse_qs(u.query)
            if u.path=='/api/queue':return self.send(queue_state())
            if u.path=='/api/nodes':return self.send(node_list())
            if u.path=='/api/jobs':return self.send(jobs(summary=qs.get('view',[''])[0]=='summary'))
            if u.path=='/api/system':
                pid=active_worker_pid()
                return self.send(dict(cpu=cpu_label(),cores=os.cpu_count(),performance_cores=performance_cores(),engine='REBOUND 5.1.1 · CPU',data_directory=str(DATA),wall_cap_hours=WALL_CAP_HOURS,max_runs=MAX_RUNS,protected=sorted(PROTECTED),reference_seconds=REFERENCE_SECONDS,
                    daemon=os.environ.get('OPENORBITAL_DAEMON')=='1',sleep_prevention='idle' if pid and shutil.which('caffeinate') else 'off',worker_pid=pid,lid_close_sleeps=True if sys.platform=='darwin' else None,engine_hash=nodes.engine_hash()))
            if u.path=='/api/schema':return self.send(dict(schema={k:dict(kind=v[0],allowed=v[1]) for k,v in SCHEMA.items()},defaults=DEFAULTS,galaxy_keys=GALAXY_KEYS,planet_keys=PLANET_KEYS))
            if len(parts)>=3 and parts[:2]==['api','jobs']:
                p=folder(parts[2]);j=job(p)
                if len(parts)==3:return self.send(j)
                if parts[3]=='log':return self.send(dict(lines=log_tail(p,max(1,min(int(qs.get('tail',[40])[0]),200)))))
                if parts[3]=='history':return self.send(history_points(p))
                if parts[3]=='twin':return self.send(twin_compare(p))
                if parts[3]=='galaxy-index':
                    g=p/'galaxy_index.bin'
                    if not g.exists():raise NotFound('No galaxy index')
                    return self.send(g.read_bytes(),mime='application/octet-stream')
                if parts[3]=='track':
                    return self.send(track_particle(p,int(qs.get('index',[0])[0]),int(qs.get('start',[0])[0])))
                if parts[3]=='frames':
                    start=int(qs.get('start',[0])[0]);count=int(qs.get('count',[1])[0]);available=j['status'].get('frames',0);n=j['meta'].get('n',0);stride=n*j['meta'].get('bytes_per_particle',16)
                    # One frame is always servable (1M × 24 B = 24 MB); the 8 MB cap only limits multi-frame batches.
                    if start<0 or count<1 or start+count>available or (count>1 and count*stride>8*1024**2):raise ValueError('Requested frames unavailable or too large')
                    with (p/'frames.bin').open('rb') as f:f.seek(start*stride);raw=f.read(count*stride)
                    if len(raw)!=count*stride:raise ValueError('Frame is not ready')
                    every=int(qs.get('every',[1])[0])
                    if not 1<=every<=64:raise ValueError('every must be between 1 and 64')
                    if every>1:
                        import numpy as np
                        per=j['meta'].get('bytes_per_particle',16)//4
                        raw=np.frombuffer(raw,'<f4').reshape(count,n,per)[:,display_sample(n,every,j['meta']),:].tobytes()
                    return self.send(raw,mime='application/octet-stream')
            page={'':'index.html','observe':'index.html','lab':'index.html','compute':'index.html'}  # one page; /lab and /compute open the composer
            rel=page.get(u.path.strip('/'),unquote(u.path.lstrip('/')));p=(BASE/'static'/rel).resolve()
            if not p.is_relative_to(BASE/'static') or not p.is_file():return self.send(dict(error='Not found'),404)
            import mimetypes
            return self.send(p.read_bytes(),mime=mimetypes.guess_type(p)[0] or 'application/octet-stream')
        except NotFound as e:self.send(dict(error=str(e)),404)
        except (ValueError,KeyError) as e:self.send(dict(error=str(e)),400)
    def do_POST(self):
        try:
            if not self.same_origin():return self.send(dict(error='Cross-origin request rejected'),403)
            size=int(self.headers.get('Content-Length',0))
            if size>8192:raise ValueError('Request too large')
            data=json.loads(self.rfile.read(size) or '{}');parts=urlparse(self.path).path.strip('/').split('/')
            if parts==['api','preview']:return self.send(preview(data),mime='application/octet-stream')
            if parts==['api','realistic']:
                cfg=normalize(dict(data,mode='galaxy',duration=float(data.get('duration') or 1),realistic=True))
                return self.send(dict(realistic_info(cfg),estimated_seconds=cfg['estimated_seconds']))
            if len(parts)==4 and parts[:2]==['api','nodes'] and parts[3]=='install-key':
                nid=parts[2];nodes.get(nid)
                if nid=='local':raise ValueError('This Mac needs no key.')
                try:return self.send(nodes.install_key(nid,data.pop('password',None)))
                except nodes.NodeError as e:return self.send(dict(error=str(e)),400)
            if len(parts)==4 and parts[:2]==['api','nodes'] and parts[3] in ('probe','benchmark'):
                nid=parts[2];nodes.get(nid)
                if nid=='local':raise ValueError('This Mac is measured by the reference estimator.')
                if parts[3]=='probe':return self.send(nodes.probe(nid))
                if busy(node=nid):raise ValueError('Benchmark would compete with the experiment running on this node.')
                nodes._bg('bench:'+nid,lambda:_safe(nodes.benchmark,nid));return self.send(dict(ok=True,started=True))
            with LOCK:
                if parts==['api','queue','jobs']:return self.send(create(data,enqueue=True),201)
                if parts==['api','queue']:return self.send(queue_action(data))
                if parts==['api','jobs']:return self.send(create(data),201)
                if parts==['api','nodes']:return self.send(nodes.save_node(data),201)
                if len(parts)==4 and parts[:2]==['api','jobs'] and parts[3]=='standby':
                    p=folder(parts[2]);nodes.set_standby(p,str(data.get('node') or '') or None,data.get('return_on_wake',True));return self.send(dict(ok=True,job=job(p,True)))
                if len(parts)==4 and parts[:2]==['api','jobs'] and parts[3]=='move':
                    p=folder(parts[2])
                    if parts[2] in PROTECTED:raise ValueError('Preserved comparison runs stay on this Mac.')
                    nodes.start_transfer(p,str(data.get('node') or ''));return self.send(dict(ok=True,job=job(p,True)))
                if len(parts)==4 and parts[:2]==['api','jobs'] and parts[3]=='control':
                    p=folder(parts[2]);action=data.get('action');j=job(p)
                    if j['status']['phase']=='queued':raise ValueError('Start queued experiments through the queue.')
                    if action not in ['pause','run']:raise ValueError('Unsupported control')
                    if j['status']['phase'] in ['complete','error']:raise ValueError('This experiment has finished')
                    node=j['location'].get('node','local')
                    if (j['location'].get('transfer') or {}).get('state') in ('pausing','copying','starting'):raise ValueError('A hand-off is in progress.')
                    if action=='run' and busy(p.name,node):raise ValueError(f'Pause the other experiment on {nodes.get(node)["label"]} first')
                    if node!='local':
                        try:nodes.send_control(p,action)
                        except nodes.NodeError as e:raise ValueError(f'{e}. Control was not delivered.')
                    atomic(p/'control.json',dict(action=action,requested_at=time.time()))
                    if action=='run' and j['status']['phase'] in ('interrupted','paused') and not alive(p.name):
                        if node=='local':spawn(p)
                        else:
                            try:
                                threads=int(j['config'].get('threads') or 1);cores=(nodes.HEALTH.get(node) or {}).get('cores') or threads
                                nodes.resume_remote(p,min(threads,cores))
                            except nodes.NodeError as e:raise ValueError(str(e))
                    updated=job(p)
                    return self.send(dict(ok=True,status=updated['status']))
            self.send(dict(error='Not found'),404)
        except subprocess.TimeoutExpired:self.send(dict(error='Preview timed out'),400)
        except NotFound as e:self.send(dict(error=str(e)),404)
        except (ValueError,KeyError,TypeError) as e:self.send(dict(error=str(e)),400)
    def do_DELETE(self):
        try:
            if not self.same_origin():return self.send(dict(error='Cross-origin request rejected'),403)
            parts=urlparse(self.path).path.strip('/').split('/')
            with LOCK:
                if len(parts)==3 and parts[:2]==['api','jobs']:return self.send(remove(parts[2]))
                if len(parts)==3 and parts[:2]==['api','nodes']:
                    nodes.delete_node(parts[2],[j['id'] for j in jobs(True) if j['location'].get('node')==parts[2]]);return self.send(dict(ok=True))
            self.send(dict(error='Not found'),404)
        except NotFound as e:self.send(dict(error=str(e)),404)
        except (ValueError,KeyError) as e:self.send(dict(error=str(e)),400)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8766);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Observatory: http://127.0.0.1:{args.port}  (/lab opens the composer)',flush=True)
    def stop(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    configure_nodes()
    recover()
    thread=threading.Thread(target=scheduler,daemon=True);thread.start()
    threading.Thread(target=nodes.loop,args=(STOP_SCHEDULER,lambda:[p for p in DATA.iterdir() if p.is_dir() and (p/'config.json').exists()]),daemon=True).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        STOP_SCHEDULER.set();thread.join(timeout=5)
        for p in PROCESSES.values():stop_proc(p)
        for p in PROCESSES.values():
            try:p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                try:
                    if not isinstance(p,Adopted) and getattr(p,'pid',None):os.killpg(p.pid,signal.SIGKILL)
                    else:p.kill()
                except OSError:pass
        server.server_close()
