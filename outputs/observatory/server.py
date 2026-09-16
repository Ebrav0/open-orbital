# AGENT MAP: HTTP handlers supervise workers; they do not integrate physics.
# Keep loopback binding, input bounds, one-active-job checks, protected runs and existing run data.
# SCHEMA here is the validation authority; static/shared.js mirrors it for the Compute page.
"""Loopback-only server and isolated CPU job manager. Stdlib HTTP, local assets."""
import os,sys,json,re,time,subprocess,threading,uuid,argparse,signal,shutil,math
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs,unquote
from worker import atomic
BASE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('OBSERVATORY_DATA',BASE.parents[1]/'work/observatory-data')).resolve();DATA.mkdir(parents=True,exist_ok=True)
PROCESSES={};LOCK=threading.Lock()
PROTECTED={'0e45a855ba11','44c528079f88','ff56d195ce89','58ab7c268cdd'}
WALL_CAP_HOURS=120;MAX_RUNS=12;ACTIVE=['running','initializing','queued','pausing']
REFERENCE_SECONDS=157.84   # measured: 100,000 particles, 10 threads, 500 steps, model revision 2

# id -> (kind, allowed) where kind is 'choice', 'float', 'int', 'bool', 'list8'
SCHEMA=dict(
    n=('choice',[10000,30000,100000,200000]),threads=('choice',[1,4,8,10,14]),seed=('int',(0,2**32-1)),
    disk_mass=('float',(.2,5)),halo_mass=('float',(2,80)),disk_fraction=('float',(.15,.45)),disk_scale=('float',(.5,3)),disk_thickness=('float',(.03,.25)),halo_scale=('float',(1.5,10)),warmth=('float',(.4,3)),smbh_mass=('float',(0,.1)),
    lifecycle_enabled=('bool',None),gas_fraction=('float',(0,.8)),t_sf=('float',(.1,20)),lifecycle_speed=('float',(1,80)),sf_density_bias=('float',(0,1)),imf_mmin=('float',(.05,1)),imf_mmax=('float',(20,150)),grow_rate=('float',(0,1)),sn_kick_kms=('float',(0,200)),
    theta=('float',(.25,.7)),softening=('float',(.03,.15)),dt=('float',(.01,.04)),
    jupiter_mass=('choice',[1,3,10]),planet_mass_scale=('list8',(.25,10)),perturber_mass=('float',(0,.01)),perturber_a=('float',(.5,40)))
GALAXY_KEYS=['n','threads','seed','disk_mass','halo_mass','disk_fraction','disk_scale','disk_thickness','halo_scale','warmth','smbh_mass','lifecycle_enabled','gas_fraction','t_sf','lifecycle_speed','sf_density_bias','imf_mmin','imf_mmax','grow_rate','sn_kick_kms','theta','softening','dt']
PLANET_KEYS=['seed','jupiter_mass','planet_mass_scale','perturber_mass','perturber_a']
DEFAULTS=dict(n=100000,threads=8,seed=731,disk_mass=1,halo_mass=20,disk_fraction=.3,disk_scale=1.2,disk_thickness=.08,halo_scale=4,warmth=1,smbh_mass=0,lifecycle_enabled=True,gas_fraction=.2,t_sf=2,lifecycle_speed=1,sf_density_bias=.7,imf_mmin=.08,imf_mmax=100,grow_rate=.2,sn_kick_kms=0,theta=.4,softening=.06,dt=.02,jupiter_mass=1,planet_mass_scale=[1]*8,perturber_mass=0,perturber_a=2.5)

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
    if status['phase'] in ['running','initializing','paused','queued','pausing'] and not alive(p.name):
        status['phase']='interrupted' if (p/'checkpoint.json').exists() else 'error';status['error']='Worker stopped. Resume the saved checkpoint.' if status['phase']=='interrupted' else 'Worker stopped before its first checkpoint.'
    status=annotate_pause(status,cfg,meta,control)
    if summary:
        meta={k:v for k,v in meta.items() if k not in ('times','bodies','initial_diagnostics','params')}
        status={k:v for k,v in status.items() if k!='flags'}
        if 'events' in status:status['events']=status['events'][-20:]
    return dict(id=p.name,config=cfg,status=status,meta=meta,protected=p.name in PROTECTED)

def jobs(summary=False):return sorted([job(p,summary) for p in DATA.iterdir() if p.is_dir() and (p/'config.json').exists()],key=lambda x:x['config'].get('created',0),reverse=True)

def busy(except_id=None):return any(j['id']!=except_id and j['status']['phase'] in ACTIVE for j in jobs(True))

def spawn(p):
    env=os.environ.copy();env['OMP_NUM_THREADS']=str(read(p/'config.json',{}).get('threads',1));env['OMP_WAIT_POLICY']='PASSIVE'
    with (p/'worker.log').open('ab') as log:PROCESSES[p.name]=subprocess.Popen([sys.executable,str(BASE/'worker.py'),str(p)],stdout=log,stderr=log,env=env)

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
    """Wall-time estimate from the measured revision-2 reference. Order-of-magnitude for lifecycle runs and 200k."""
    if cfg['mode']=='planets':
        bodies=10 if cfg.get('perturber_mass',0)>0 else 9
        return .25*cfg['duration']/12*(bodies/9)**2
    n=cfg['n'];steps=cfg['duration']/cfg['dt']
    return REFERENCE_SECONDS*(n/1e5)*math.log(n)/math.log(1e5)*(steps/500)*(10/cfg['threads'])*(1.15 if cfg.get('lifecycle_enabled') else 1)

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
    cfg['duration']=duration
    est=estimate_seconds(cfg)
    if est>WALL_CAP_HOURS*3600:
        unit='model time units' if mode=='galaxy' else 'years'
        raise ValueError(f'Estimated {est/3600:.0f} h exceeds the {WALL_CAP_HOURS}-hour compute cap. Maximum span for these settings is about {max_duration(cfg):.1f} {unit}.')
    notes=str(config.get('notes',''))[:2000]
    cfg.update(notes=notes,estimated_seconds=est,created=time.time())
    return cfg

def create(config):
    cfg=normalize(config)
    if busy():raise ValueError('Pause the running experiment before starting another.')
    if len(jobs(True))>=MAX_RUNS:raise ValueError(f'{MAX_RUNS} experiments are saved. Remove a run before creating more.')
    need=disk_bytes(cfg)+2*1024**3
    if shutil.disk_usage(DATA).free<need:raise ValueError(f'At least {need/1024**3:.1f} GiB of free disk space is required for this run.')
    jid=uuid.uuid4().hex[:12];p=DATA/jid;p.mkdir();atomic(p/'config.json',cfg);atomic(p/'control.json',dict(action='run'));spawn(p);return job(p)

def remove(jid):
    if jid in PROTECTED:raise ValueError('This experiment is a preserved comparison run and cannot be removed.')
    p=folder(jid);j=job(p,True);phase=j['status']['phase']
    if phase in ACTIVE:raise ValueError('Pause or finish this experiment before removing it.')
    proc=PROCESSES.pop(jid,None)
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:proc.wait(timeout=20)
        except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
    shutil.rmtree(p)
    return dict(ok=True,removed=jid)

def preview(config):
    """Initial conditions only, 8,000 particles, in a subprocess with a timeout. Returns one xyzsmt frame."""
    cfg=normalize(dict(config,n=10000,threads=1,duration=1));cfg['n']=8000
    code='import sys,json,numpy as np;from physics import galaxy,planets,arrays;import stellar\ncfg=json.load(sys.stdin)\n' \
         's,meta,b=galaxy(**{k:v for k,v in cfg.items() if k in %r}) if cfg["mode"]=="galaxy" else planets(cfg.get("jupiter_mass",1),cfg.get("planet_mass_scale"),cfg.get("perturber_mass",0),cfg.get("perturber_a",2.5))\n' \
         'q,m=arrays(s);t=(b["type"] if b is not None else np.where(np.arange(s.N)<meta.get("disk_count",s.N),2,7)).astype(np.float32)\n' \
         'sys.stdout.buffer.write(np.column_stack((q[:,:3],np.linalg.norm(q[:,3:],axis=1),m,t)).astype("<f4").tobytes())'%GALAXY_KEYS
    r=subprocess.run([sys.executable,'-c',code],input=json.dumps(cfg).encode(),capture_output=True,timeout=5,cwd=BASE,env=dict(os.environ,OMP_NUM_THREADS='1'))
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
            if u.path=='/api/jobs':return self.send(jobs(summary=qs.get('view',[''])[0]=='summary'))
            if u.path=='/api/system':return self.send(dict(cpu='Apple M4 Pro',cores=os.cpu_count(),engine='REBOUND 5.1.1 · CPU',data_directory=str(DATA),wall_cap_hours=WALL_CAP_HOURS,max_runs=MAX_RUNS,protected=sorted(PROTECTED),reference_seconds=REFERENCE_SECONDS))
            if u.path=='/api/schema':return self.send(dict(schema={k:dict(kind=v[0],allowed=v[1]) for k,v in SCHEMA.items()},defaults=DEFAULTS,galaxy_keys=GALAXY_KEYS,planet_keys=PLANET_KEYS))
            if len(parts)>=3 and parts[:2]==['api','jobs']:
                p=folder(parts[2]);j=job(p)
                if len(parts)==3:return self.send(j)
                if parts[3]=='log':return self.send(dict(lines=log_tail(p,max(1,min(int(qs.get('tail',[40])[0]),200)))))
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
                if parts==['api','jobs']:return self.send(create(data),201)
                if len(parts)==4 and parts[:2]==['api','jobs'] and parts[3]=='control':
                    p=folder(parts[2]);action=data.get('action');j=job(p)
                    if action not in ['pause','run']:raise ValueError('Unsupported control')
                    if j['status']['phase'] in ['complete','error']:raise ValueError('This experiment has finished')
                    if action=='run' and busy(p.name):raise ValueError('Pause the other running experiment first')
                    atomic(p/'control.json',dict(action=action,requested_at=time.time()))
                    if j['status']['phase']=='interrupted' and action=='run':spawn(p)
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
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        for p in PROCESSES.values():
            if p.poll() is None:p.terminate()
        for p in PROCESSES.values():
            try:p.wait(timeout=20)
            except subprocess.TimeoutExpired:p.kill()
        server.server_close()
