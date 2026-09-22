# AGENT MAP: HTTP handlers supervise workers; they do not integrate physics.
# Keep loopback binding, input bounds, one-active-job checks, protected runs and existing run data.
# SCHEMA here is the validation authority; static/shared.js mirrors it for the Compute page.
"""Loopback-only server and isolated CPU job manager. Stdlib HTTP, local assets."""
import os,sys,json,re,time,subprocess,threading,uuid,argparse,signal,shutil,math,struct
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs,unquote
from worker import atomic
BASE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('OBSERVATORY_DATA',BASE.parents[1]/'work/observatory-data')).resolve();DATA.mkdir(parents=True,exist_ok=True)
PROCESSES={};LOCK=threading.Lock()
PROTECTED={'0e45a855ba11','44c528079f88','ff56d195ce89','58ab7c268cdd'}
WALL_CAP_HOURS=120;MAX_RUNS=24;ACTIVE=['running','initializing','pausing']
REFERENCE_SECONDS=157.84   # measured: 100,000 particles, 10 threads, 500 steps, model revision 2

CLONE_AZIMUTH={2:0,3:120,4:240,5:180}
# id -> (kind, allowed) where kind is 'choice', 'float', 'int', 'bool', 'list8'
SCHEMA=dict(
    n=('choice',[10000,30000,100000,200000,500000,1000000]),threads=('choice',[1,4,8,10,14]),seed=('int',(0,2**32-1)),
    n_galaxies=('choice',[1,2,3,4,5]),
    disk_mass=('float',(.2,5)),halo_mass=('float',(2,80)),disk_fraction=('float',(.15,.45)),disk_scale=('float',(.5,3)),disk_thickness=('float',(.03,.25)),halo_scale=('float',(1.5,10)),warmth=('float',(.4,3)),smbh_mass=('float',(0,.1)),
    lifecycle_enabled=('bool',None),gas_fraction=('float',(0,.8)),t_sf=('float',(.1,20)),lifecycle_speed=('float',(1,80)),sf_density_bias=('float',(0,1)),imf_mmin=('float',(.05,1)),imf_mmax=('float',(20,150)),grow_rate=('float',(0,1)),sn_kick_kms=('float',(0,200)),
    ism_enabled=('bool',None),metallicity=('float',(0,3)),cooling_speed=('float',(0,4)),sn_feedback=('float',(0,1)),ram_pressure=('float',(0,3)),n_sf=('float',(.01,5)),
    sn_momentum=('float',(0,2)),cloud_dissipation=('float',(0,4)),metal_diffusion=('float',(0,3)),fuv_heating=('float',(0,4)),noneq_ionization=('bool',None),
    theta=('float',(.25,.7)),softening=('float',(.03,.15)),dt=('float',(.01,.04)),
    jupiter_mass=('choice',[1,3,10]),planet_mass_scale=('list8',(.25,10)),perturber_mass=('float',(0,.01)),perturber_a=('float',(.5,40)))
for _i in range(2,6):
    SCHEMA[f'g{_i}_mass_ratio']=('float',(.1,3));SCHEMA[f'g{_i}_size_ratio']=('float',(.3,2))
    SCHEMA[f'g{_i}_sep']=('float',(8,80));SCHEMA[f'g{_i}_impact']=('float',(0,20));SCHEMA[f'g{_i}_vrel']=('float',(.4,4))
    SCHEMA[f'g{_i}_azimuth']=('float',(0,360));SCHEMA[f'g{_i}_inclination']=('float',(0,180));SCHEMA[f'g{_i}_disk_tilt']=('float',(0,180))
    SCHEMA[f'g{_i}_spin']=('choice',[1,-1])
_CLONE_KEYS=[k for i in range(2,6) for k in (f'g{i}_mass_ratio',f'g{i}_size_ratio',f'g{i}_sep',f'g{i}_impact',f'g{i}_vrel',f'g{i}_azimuth',f'g{i}_inclination',f'g{i}_disk_tilt',f'g{i}_spin')]
GALAXY_KEYS=['n','threads','seed','n_galaxies']+_CLONE_KEYS+['disk_mass','halo_mass','disk_fraction','disk_scale','disk_thickness','halo_scale','warmth','smbh_mass','lifecycle_enabled','gas_fraction','t_sf','lifecycle_speed','sf_density_bias','imf_mmin','imf_mmax','grow_rate','sn_kick_kms','ism_enabled','metallicity','cooling_speed','sn_feedback','ram_pressure','n_sf','sn_momentum','cloud_dissipation','metal_diffusion','fuv_heating','noneq_ionization','theta','softening','dt']
PLANET_KEYS=['seed','jupiter_mass','planet_mass_scale','perturber_mass','perturber_a']
DEFAULTS=dict(n=100000,threads=8,seed=731,n_galaxies=2,disk_mass=1,halo_mass=20,disk_fraction=.3,disk_scale=1.2,disk_thickness=.08,halo_scale=4,warmth=1,smbh_mass=0,lifecycle_enabled=True,gas_fraction=.2,t_sf=2,lifecycle_speed=1,sf_density_bias=.7,imf_mmin=.08,imf_mmax=100,grow_rate=.2,sn_kick_kms=0,ism_enabled=True,metallicity=1,cooling_speed=1,sn_feedback=.15,ram_pressure=1,n_sf=.1,sn_momentum=.4,cloud_dissipation=1,metal_diffusion=.6,fuv_heating=1,noneq_ionization=True,theta=.4,softening=.06,dt=.02,jupiter_mass=1,planet_mass_scale=[1]*8,perturber_mass=0,perturber_a=2.5)
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
    proc=PROCESSES.get(jid);return proc is not None and proc.poll() is None

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
    control=read(p/'control.json',{})
    if status['phase'] in ['running','initializing','pausing'] and not alive(p.name):
        if (p/'checkpoint.json').exists():
            status['phase']='paused' if control.get('action')=='pause' else 'interrupted'
            status['error']='Worker stopped. Resume the saved checkpoint.' if status['phase']=='interrupted' else status.get('error')
            if status['phase']=='paused' and 'error' in status:status.pop('error',None)
        else:
            status['phase']='error';status['error']='Worker stopped before its first checkpoint.'
    status=annotate_pause(status,cfg,meta,control)
    ck=p/'checkpoint.json'
    if ck.exists():
        try:status['checkpoint_age_seconds']=time.time()-ck.stat().st_mtime
        except OSError:pass
    if summary:
        meta={k:v for k,v in meta.items() if k not in ('times','bodies','initial_diagnostics','params')}
        status={k:v for k,v in status.items() if k!='flags'}
        if 'events' in status:status['events']=status['events'][-20:]
    return dict(id=p.name,config=cfg,status=status,meta=meta,protected=p.name in PROTECTED)

def jobs(summary=False):return sorted([job(p,summary) for p in DATA.iterdir() if p.is_dir() and (p/'config.json').exists()],key=lambda x:x['config'].get('created',0),reverse=True)

def busy(except_id=None):
    if any(jid!=except_id and proc is not None and proc.poll() is None for jid,proc in PROCESSES.items()):return True
    return any(j['id']!=except_id and j['status']['phase'] in ACTIVE for j in jobs(True))

def pid_running(pid):
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
    if adopt(p):return
    env=os.environ.copy();env['OMP_NUM_THREADS']=str(read(p/'config.json',{}).get('threads',1));env['OMP_WAIT_POLICY']='PASSIVE'
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

def estimate_seconds(cfg):
    """Wall-time estimate from the measured revision-2 100k/10-thread reference. Order-of-magnitude for lifecycle, 500k and 1M."""
    if cfg['mode']=='planets':
        bodies=10 if cfg.get('perturber_mass',0)>0 else 9
        return .25*cfg['duration']/12*(bodies/9)**2
    n=cfg['n'];steps=cfg['duration']/cfg['dt']
    extra=1.05 if int(cfg.get('n_galaxies') or 1)>1 else 1
    lc=1.15 if cfg.get('lifecycle_enabled') else 1
    ism=1.18 if cfg.get('lifecycle_enabled') and cfg.get('ism_enabled',True) else 1
    return REFERENCE_SECONDS*(n/1e5)*math.log(n)/math.log(1e5)*(steps/500)*(10/cfg['threads'])*lc*ism*extra

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

def track_particle(p,index):
    j=job(p);n=int(j['meta'].get('n') or j['config'].get('n') or 0);frames=int(j['status'].get('frames') or 0)
    stride=int(j['meta'].get('bytes_per_particle') or 16)
    if index<0 or index>=n:raise ValueError('Particle index out of range')
    if frames>8000:raise ValueError('Track too long')
    times=j['meta'].get('times') or [];galaxy=None
    gpath=p/'galaxy_index.bin'
    if gpath.exists():
        raw=gpath.read_bytes()
        if index<len(raw):galaxy=int(raw[index])
    points=[]
    path=p/'frames.bin'
    if not path.exists() or not n or not frames:return dict(index=index,galaxy=galaxy,n=n,points=[])
    with path.open('rb') as f:
        for i in range(frames):
            f.seek(i*n*stride+index*stride);buf=f.read(stride)
            if len(buf)!=stride:break
            vals=struct.unpack('<'+'f'*(stride//4),buf)
            rec=dict(frame=i,t=times[i] if i<len(times) else None,x=vals[0],y=vals[1],z=vals[2])
            if len(vals)>3:rec['speed']=vals[3]
            if len(vals)>4:rec['mass']=vals[4]
            if len(vals)>5:rec['type']=vals[5]
            points.append(rec)
    return dict(index=index,galaxy=galaxy,n=n,points=points)

def queue_state():
    return read(QUEUE_FILE,dict(enabled=False,ids=[],current=None,message='Ready to arrange experiments.'))

def save_queue(q):atomic(QUEUE_FILE,q)

def check_space(cfg,queued=()):
    need=disk_bytes(cfg)+sum(disk_bytes(read(folder(jid)/'config.json',{})) for jid in queued)+2*1024**3
    if shutil.disk_usage(DATA).free<need:raise ValueError(f'At least {need/1024**3:.1f} GiB of free disk space is required for these experiments.')

def create(config,enqueue=False):
    cfg=normalize(config);q=queue_state()
    if not enqueue and (busy() or q['enabled']):raise ValueError('Pause the running experiment or hold the queue before starting another.')
    if len(jobs(True))>=MAX_RUNS:raise ValueError(f'{MAX_RUNS} experiments are saved. Remove a run before creating more.')
    check_space(cfg,q['ids'])
    jid=uuid.uuid4().hex[:12];p=DATA/jid;p.mkdir();atomic(p/'config.json',cfg);atomic(p/'control.json',dict(action='run'))
    atomic(p/'status.json',dict(phase='queued' if enqueue else 'initializing',frames=0,progress=0))
    if enqueue:
        q['ids'].append(jid);save_queue(q)
    else:spawn(p)
    return job(p)

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
    # A live worker — including a paused one still in its wait loop — blocks dispatch.
    for j in jobs(True):
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
    except OSError as e:
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
    shutil.rmtree(p)
    return dict(ok=True,removed=jid)

def preview(config):
    """Initial conditions only, 8,000 particles, in a subprocess with a timeout. Returns one xyzsmt frame."""
    cfg=normalize(dict(config,n=10000,threads=1,duration=1));cfg['n']=8000
    code='import sys,json,numpy as np;from physics import galaxy,planets,arrays;import stellar\ncfg=json.load(sys.stdin)\n' \
         's,meta,b=galaxy(**{k:v for k,v in cfg.items() if k in %r}) if cfg["mode"]=="galaxy" else planets(cfg.get("jupiter_mass",1),cfg.get("planet_mass_scale"),cfg.get("perturber_mass",0),cfg.get("perturber_a",2.5))\n' \
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
    path=p/'worker.log'
    if not path.exists():return []
    with path.open('rb') as f:
        f.seek(0,2);size=f.tell();f.seek(max(0,size-32*1024));data=f.read()
    return data.decode(errors='replace').splitlines()[-tail:]

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
            if u.path=='/api/jobs':return self.send(jobs(summary=qs.get('view',[''])[0]=='summary'))
            if u.path=='/api/system':
                pid=active_worker_pid()
                return self.send(dict(cpu='Apple M4 Pro',cores=os.cpu_count(),engine='REBOUND 5.1.1 · CPU',data_directory=str(DATA),wall_cap_hours=WALL_CAP_HOURS,max_runs=MAX_RUNS,protected=sorted(PROTECTED),reference_seconds=REFERENCE_SECONDS,
                    daemon=os.environ.get('OPENORBITAL_DAEMON')=='1',sleep_prevention='idle' if pid else 'off',worker_pid=pid,lid_close_sleeps=True))
            if u.path=='/api/schema':return self.send(dict(schema={k:dict(kind=v[0],allowed=v[1]) for k,v in SCHEMA.items()},defaults=DEFAULTS,galaxy_keys=GALAXY_KEYS,planet_keys=PLANET_KEYS))
            if len(parts)>=3 and parts[:2]==['api','jobs']:
                p=folder(parts[2]);j=job(p)
                if len(parts)==3:return self.send(j)
                if parts[3]=='log':return self.send(dict(lines=log_tail(p,max(1,min(int(qs.get('tail',[40])[0]),200)))))
                if parts[3]=='history':return self.send(history_points(p))
                if parts[3]=='galaxy-index':
                    g=p/'galaxy_index.bin'
                    if not g.exists():raise NotFound('No galaxy index')
                    return self.send(g.read_bytes(),mime='application/octet-stream')
                if parts[3]=='track':
                    return self.send(track_particle(p,int(qs.get('index',[0])[0])))
                if parts[3]=='frames':
                    start=int(qs.get('start',[0])[0]);count=int(qs.get('count',[1])[0]);available=j['status'].get('frames',0);n=j['meta'].get('n',0);stride=n*j['meta'].get('bytes_per_particle',16)
                    if start<0 or count<1 or start+count>available or count*stride>8*1024**2:raise ValueError('Requested frames unavailable or too large')
                    with (p/'frames.bin').open('rb') as f:f.seek(start*stride);raw=f.read(count*stride)
                    if len(raw)!=count*stride:raise ValueError('Frame is not ready')
                    return self.send(raw,mime='application/octet-stream')
            page={'':'index.html','observe':'index.html','lab':'lab.html','compute':'lab.html'}
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
            with LOCK:
                if parts==['api','queue','jobs']:return self.send(create(data,enqueue=True),201)
                if parts==['api','queue']:return self.send(queue_action(data))
                if parts==['api','jobs']:return self.send(create(data),201)
                if len(parts)==4 and parts[:2]==['api','jobs'] and parts[3]=='control':
                    p=folder(parts[2]);action=data.get('action');j=job(p)
                    if j['status']['phase']=='queued':raise ValueError('Start queued experiments through the queue.')
                    if action not in ['pause','run']:raise ValueError('Unsupported control')
                    if j['status']['phase'] in ['complete','error']:raise ValueError('This experiment has finished')
                    if action=='run' and busy(p.name):raise ValueError('Pause the other running experiment first')
                    atomic(p/'control.json',dict(action=action,requested_at=time.time()))
                    if action=='run' and j['status']['phase'] in ('interrupted','paused'):spawn(p)
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
            self.send(dict(error='Not found'),404)
        except NotFound as e:self.send(dict(error=str(e)),404)
        except (ValueError,KeyError) as e:self.send(dict(error=str(e)),400)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8766);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Observatory: http://127.0.0.1:{args.port}  (Compute page: /lab)',flush=True)
    def stop(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    recover()
    thread=threading.Thread(target=scheduler,daemon=True);thread.start()
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
