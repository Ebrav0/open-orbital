# AGENT MAP: compute nodes. The Mac server stays the hub. A remote run keeps a mirror folder under DATA
# (config, control and location.json are authoritative here) and a work folder on the node where worker.py runs.
# SSH is key-only (BatchMode). The one exception is install_key(): a password typed in the UI is used once to append
# this Mac's public key to the node's authorized_keys, then discarded. Never store or reuse passwords.
# Frames on the Mac are what Observe reads: status.json is written here only after the frames it advertises.
# A hand-off pauses at a checkpoint, moves the checkpoint and small files (never old frames), and resumes on the target.
import os,re,io,json,time,shlex,shutil,hashlib,tarfile,threading,subprocess
from pathlib import Path

BASE=Path(__file__).resolve().parent
NODES_FILE=Path(os.environ.get('OBSERVATORY_NODES',BASE.parents[1]/'work/nodes.json'))
ENGINE_FILES=('physics.py','stellar.py','worker.py','realistic.py')
SMALL_PULL=('meta.json','status.json','checkpoint.json','diagnostics.jsonl','galaxy_index.bin','model_source.py','stellar_source.py','realistic_source.py')
PUSH_SKIP={'frames.bin','worker.log','worker.pid','location.json','remote.log'}
ID_RE=re.compile(r'[a-z0-9][a-z0-9-]{0,31}')
HOST_RE=re.compile(r'([A-Za-z0-9._-]+@)?[A-Za-z0-9._-]+')
PATH_RE=re.compile(r'(~/|/)?[A-Za-z0-9._/-]+')
FRAME_PULL_CAP=256*1024**2          # bytes per sync pass, so one huge backlog does not starve other jobs
FINAL_PHASES=('paused','interrupted','complete','error')
# Speed factors multiply the Mac estimator at the same thread count. They come from one measurement each.
DEFAULT_NODES=[dict(id='computenode1',label='computenode1',host='Edb@computenode1',root='~/open-orbital',
    python='work/venv/bin/python',pythonpath='work/openmp',runs='work/remote-runs',always_on=True,speed=6.21,
    speed_source='Measured 2026-09-23: 1,000,000 particles, 2 galaxies, 4 threads: 51.36 s/step on the node vs 8.27 s/step on the Mac (work/node-comparison).')]

REMOTE={}      # jid -> dict(alive, synced_at, reachable, error, spawned_at)
HEALTH={}      # node id -> probe result
BENCH={}       # node id -> 'running' | 'done' | 'failed: …'
_THREADS={};_TLOCK=threading.Lock();_FILE_LOCK=threading.Lock()
HOOKS={}       # set by server.configure(): data, atomic, spawn_local, stop_local, alive_local, busy, reference_seconds

class NodeError(RuntimeError):pass

def _read(p,default):
    try:return json.loads(Path(p).read_text())
    except (FileNotFoundError,ValueError):return default

# ---------- registry ----------
def registry():
    with _FILE_LOCK:
        data=_read(NODES_FILE,None)
        if data is None:
            data=dict(nodes=DEFAULT_NODES)
            NODES_FILE.parent.mkdir(parents=True,exist_ok=True);HOOKS['atomic'](NODES_FILE,data)
        return data['nodes']

def get(node_id):
    if node_id=='local':return dict(id='local',label='This Mac',kind='local',always_on=False,speed=1.0)
    for n in registry():
        if n['id']==node_id:return dict(n,kind='ssh')
    raise ValueError(f'Unknown compute node {node_id!r}')

def validate_node(data):
    out={}
    for key,rx in (('id',ID_RE),('host',HOST_RE),('root',PATH_RE),('python',PATH_RE),('pythonpath',PATH_RE),('runs',PATH_RE)):
        v=str(data.get(key,'')).strip()
        if key in ('python','pythonpath','runs') and not v:v={'python':'work/venv/bin/python','pythonpath':'work/openmp','runs':'work/remote-runs'}[key]
        if key=='root' and not v:v='~/open-orbital'
        if not rx.fullmatch(v) or '..' in v:raise ValueError(f'Invalid node {key}: {v!r}')
        out[key]=v
    if out['id']=='local':raise ValueError('"local" is reserved for this Mac.')
    if out['root']=='~' or not (out['root'].startswith('/') or out['root'].startswith('~/')):raise ValueError('Node root must be absolute or start with ~/')
    out['label']=str(data.get('label') or out['id'])[:40]
    out['always_on']=bool(data.get('always_on',True))
    return out

def save_node(data):
    node=validate_node(data)
    with _FILE_LOCK:
        doc=_read(NODES_FILE,dict(nodes=DEFAULT_NODES));nodes=doc['nodes']
        old=next((n for n in nodes if n['id']==node['id']),None)
        if old:
            # A changed host or interpreter invalidates the measured speed.
            keep=all(old.get(k)==node[k] for k in ('host','root','python','pythonpath'))
            node.update({k:old[k] for k in ('speed','speed_source') if keep and k in old})
            nodes[nodes.index(old)]=node
        else:nodes.append(node)
        HOOKS['atomic'](NODES_FILE,doc)
    HEALTH.pop(node['id'],None)
    return node

def delete_node(node_id,jobs_on_node):
    if jobs_on_node:raise ValueError(f'{len(jobs_on_node)} experiment(s) live on {node_id}. Move or remove them first.')
    with _FILE_LOCK:
        doc=_read(NODES_FILE,dict(nodes=DEFAULT_NODES));before=len(doc['nodes'])
        doc['nodes']=[n for n in doc['nodes'] if n['id']!=node_id]
        if len(doc['nodes'])==before:raise ValueError(f'Unknown compute node {node_id!r}')
        HOOKS['atomic'](NODES_FILE,doc)
    HEALTH.pop(node_id,None)

def _update_node(node_id,**fields):
    with _FILE_LOCK:
        doc=_read(NODES_FILE,dict(nodes=DEFAULT_NODES))
        for n in doc['nodes']:
            if n['id']==node_id:n.update(fields)
        HOOKS['atomic'](NODES_FILE,doc)

# ---------- ssh transport ----------
def ssh_cmd(node):
    return ['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=4',
            '-o','StrictHostKeyChecking=accept-new','-o','LogLevel=ERROR',node['host']]

def _err(node,stderr):
    lines=[l for l in stderr.decode(errors='replace').strip().splitlines() if l.strip()]
    text=lines[-1] if lines else 'ssh failed'
    if 'Permission denied' in text:text+=' — enter the node password below once to install this Mac\'s key (or run ssh-copy-id).'
    return NodeError(f"{node['label']}: {text}")

def _public_key():
    ssh_dir=Path.home()/'.ssh'
    for name in ('id_ed25519','id_ecdsa','id_rsa'):
        if (ssh_dir/(name+'.pub')).is_file():return (ssh_dir/(name+'.pub')).read_text().strip()
    ssh_dir.mkdir(mode=0o700,exist_ok=True)
    r=subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-C','open-orbital','-f',str(ssh_dir/'id_ed25519')],capture_output=True,timeout=30)
    if r.returncode!=0:raise NodeError('Could not create an SSH key on this Mac: '+r.stderr.decode(errors='replace').strip())
    return (ssh_dir/'id_ed25519.pub').read_text().strip()

def install_key(node_id,password):
    """One-time ssh-copy-id: the password reaches ssh through SSH_ASKPASS in the child's environment only.
    It is never written to disk, logged, stored or reused; afterwards every connection is key-only again."""
    node=get(node_id)
    if not isinstance(password,str) or not password or len(password)>1024:raise ValueError('Enter the node password.')
    key=_public_key()
    # Record the state before repairing it, so a lost key (vs. bad permissions sshd's StrictModes rejects) is diagnosable.
    script=('IFS= read -r k; A="$HOME/.ssh/authorized_keys"; '
            'echo "before: $(stat -c "%A %U" "$HOME" 2>&1) home; $(stat -c "%A %U" "$HOME/.ssh" 2>&1) .ssh; '
            '$(stat -c "%A %U %y" "$A" 2>&1) authorized_keys; lines=$(wc -l < "$A" 2>/dev/null); key_present=$(grep -cxF "$k" "$A" 2>/dev/null)"; '
            'echo "sshd: $(sudo -n sshd -T 2>/dev/null | grep -iE "^(authorizedkeysfile|pubkeyauthentication|strictmodes) " | tr "\\n" " ")"; '
            'umask 077; chmod go-w "$HOME"; mkdir -p "$HOME/.ssh"; touch "$A"; '
            'grep -qxF "$k" "$A" || printf "%s\\n" "$k" >> "$A"; chmod 700 "$HOME/.ssh"; chmod 600 "$A"')
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        askpass=Path(tmp)/'askpass.sh';askpass.write_text('#!/bin/sh\nprintf "%s\\n" "$OO_SSH_PASSWORD"\n');askpass.chmod(0o700)
        env=dict(os.environ,SSH_ASKPASS=str(askpass),SSH_ASKPASS_REQUIRE='force',DISPLAY=os.environ.get('DISPLAY',':0'),OO_SSH_PASSWORD=password)
        cmd=['ssh','-o','BatchMode=no','-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password,keyboard-interactive',
             '-o','NumberOfPasswordPrompts=1','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=accept-new','-o','LogLevel=ERROR',
             node['host'],'sh -c '+shlex.quote(script)]
        # start_new_session detaches the terminal so ssh cannot fall back to prompting on the server's tty.
        try:r=subprocess.run(cmd,input=(key+'\n').encode(),capture_output=True,timeout=40,env=env,start_new_session=True)
        except subprocess.TimeoutExpired:raise NodeError(f"{node['label']}: timed out after 40 s")
        finally:env.pop('OO_SSH_PASSWORD',None);password=None
    if r.returncode!=0:
        lines=[l for l in r.stderr.decode(errors='replace').strip().splitlines() if l.strip()]
        text=lines[-1] if lines else 'ssh failed'
        if 'Permission denied' in text:text='Password rejected, or the node does not allow password sign-in (PasswordAuthentication no).'
        raise NodeError(f"{node['label']}: {text}")
    diag=r.stdout.decode(errors='replace').strip()
    print(f"[install-key {node_id} {time.strftime('%F %T')}] {diag}",flush=True)   # server.log; contains no secrets
    return dict(probe(node_id),key_install=diag)

def ssh(node,script,data=None,timeout=60):
    try:r=subprocess.run(ssh_cmd(node)+['sh -c '+shlex.quote(script)],input=data,capture_output=True,timeout=timeout)
    except subprocess.TimeoutExpired:raise NodeError(f"{node['label']}: timed out after {timeout} s")
    if r.returncode!=0:raise _err(node,r.stderr)
    return r.stdout

def rpath(node,*parts):
    """Shell-safe remote path. Values were validated by validate_node; ~/ expands through $HOME."""
    first=parts[0]
    if first.startswith('/'):return shlex.quote('/'.join(parts))
    root=node['root']
    rest='/'.join([root[2:]] if root.startswith('~/') else [root])
    rest='/'.join([rest]+list(parts))
    return '"$HOME"/'+shlex.quote(rest) if root.startswith('~/') else shlex.quote(rest)

def jobdir(node,jid):return rpath(node,node['runs'],'jobs',jid)

def push(node,dest,files,pre='',timeout=1800):
    """Stream a tar of (arcname, Path|bytes) into dest on the node."""
    cmd=ssh_cmd(node)+['sh -c '+shlex.quote(f'{pre}mkdir -p {dest} && tar -xf - -C {dest}')]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=proc.stdin,mode='w|',format=tarfile.GNU_FORMAT) as t:
            for name,src in files:
                if isinstance(src,bytes):
                    info=tarfile.TarInfo(name);info.size=len(src);info.mtime=int(time.time());info.mode=0o644
                    t.addfile(info,io.BytesIO(src))
                else:t.add(str(src),arcname=name,recursive=False)
        proc.stdin.close()
    except BrokenPipeError:pass
    try:rc=proc.wait(timeout)
    except subprocess.TimeoutExpired:proc.kill();raise NodeError(f"{node['label']}: upload timed out")
    err=proc.stderr.read()
    if rc!=0:raise _err(node,err)

def pull(node,src,names,dest,pre='',timeout=1800):
    """Tar the named files that exist under src on the node and extract them into dest. Returns names received."""
    listed=' '.join(shlex.quote(n) for n in names)
    script=f'cd {src} || exit 3\n{pre}\nset --\nfor f in {listed}; do [ -f "$f" ] && set -- "$@" "$f"; done\n[ $# -eq 0 ] && exit 0\ntar -cf - "$@"'
    proc=subprocess.Popen(ssh_cmd(node)+['sh -c '+shlex.quote(script)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    got=[];dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    try:
        with tarfile.open(fileobj=proc.stdout,mode='r|') as t:
            for m in t:
                if not m.isfile() or '/' in m.name or m.name.startswith('..'):continue
                t.extract(m,dest,filter='data');got.append(m.name)
    except tarfile.ReadError:pass
    try:rc=proc.wait(timeout)
    except subprocess.TimeoutExpired:proc.kill();raise NodeError(f"{node['label']}: download timed out")
    err=proc.stderr.read()
    if rc!=0:raise _err(node,err)
    return got

# ---------- engine + probe ----------
def engine_hash():
    h=hashlib.sha256()
    for f in ENGINE_FILES:h.update((BASE/f).read_bytes())
    return h.hexdigest()[:12]

def ensure_engine(node):
    """The node runs the Mac's exact ENGINE_FILES (physics, stellar, worker, realistic), keyed by content hash."""
    h=engine_hash();d=rpath(node,node['runs'],'engine',h)
    out=ssh(node,f'test -f {d}/worker.py && echo have || echo need').decode().strip()
    if out!='have':
        push(node,d+'.tmp',[(f,BASE/f) for f in ENGINE_FILES],pre=f'rm -rf {d}.tmp && ')
        ssh(node,f'test -f {d}/worker.py || mv {d}.tmp {d}; rm -rf {d}.tmp')
    return d

def _pyenv(node):
    py=node['python'];pp=node['pythonpath']
    return (shlex.quote(py) if py.startswith('/') else rpath(node,py)),(shlex.quote(pp) if pp.startswith('/') else rpath(node,pp))

def probe(node_id):
    node=get(node_id);started=time.time()
    py,pp=_pyenv(node);runs=rpath(node,node['runs'])
    script=(f'mkdir -p {runs}\n'
        'echo "cores=$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN)"\n'
        'echo "arch=$(uname -m)"\n'
        'echo "load=$(cut -d" " -f1 /proc/loadavg 2>/dev/null)"\n'
        'echo "mem_mb=$(awk \'/MemAvailable/{print int($2/1024)}\' /proc/meminfo 2>/dev/null)"\n'
        f'echo "disk_kb=$(df -Pk {runs} | awk \'NR==2{{print $4}}\')"\n'
        f'PYTHONPATH={pp} {py} -c \'import sys,numpy,scipy,rebound;print("python="+sys.version.split()[0]);print("rebound="+rebound.__version__)\' 2>&1 | tail -2 | sed "s/^/py:/"\n')
    h=dict(id=node_id,checked_at=started)
    try:
        for line in ssh(node,script,timeout=25).decode(errors='replace').splitlines():
            if line.startswith('py:'):
                line=line[3:]
                if '=' not in line or line.split('=')[0] not in ('python','rebound'):h['python_error']=line[-200:];continue
            k,_,v=line.partition('=')
            if k in ('cores','mem_mb','disk_kb'):h[k]=int(v) if v.strip().isdigit() else None
            elif k=='load':
                try:h[k]=float(v)
                except ValueError:h[k]=None
            elif k in ('arch','python','rebound'):h[k]=v.strip()
        h['reachable']=True;h['latency_ms']=round((time.time()-started)*1000)
        h['ready']=bool(h.get('rebound')) and not h.get('python_error')
        if h.get('rebound') and h['rebound']!=_local_rebound():
            h['warning']=f"REBOUND {h['rebound']} on the node vs {_local_rebound()} here; checkpoints may not move between them."
    except (NodeError,OSError) as e:
        h.update(reachable=False,ready=False,error=str(e))
    HEALTH[node_id]=h;return h

def _local_rebound():
    try:
        import rebound;return rebound.__version__
    except Exception:return None

def benchmark(node_id):
    """Measured seconds per step for 100,000 particles, 2 galaxies, lifecycle off, all node cores."""
    node=get(node_id);h=probe(node_id)
    if not h.get('ready'):raise NodeError(h.get('error') or h.get('python_error') or 'Node is not ready.')
    threads=max(1,int(h.get('cores') or 1));eng=ensure_engine(node);py,pp=_pyenv(node)
    code=('import sys,time,json;sys.path.insert(0,sys.argv[1]);from physics import galaxy,set_threads;u=set_threads(int(sys.argv[2]))\n'
          's,m,b=galaxy(n=100000,n_galaxies=2,lifecycle_enabled=False);s.steps(1);t=time.perf_counter();s.steps(3)\n'
          'print(json.dumps(dict(threads=u,seconds_per_step=(time.perf_counter()-t)/3)))')
    BENCH[node_id]='running'
    try:
        out=ssh(node,f'export OMP_NUM_THREADS={threads} OMP_DYNAMIC=false OMP_WAIT_POLICY=PASSIVE PYTHONPATH={pp}; {py} -c {shlex.quote(code)} {eng} {threads}',timeout=900)
        r=json.loads(out.decode().strip().splitlines()[-1])
    except Exception as e:
        BENCH[node_id]=f'failed: {e}';raise
    # Estimator for the same workload on this Mac: reference s/step × (10/threads) × 1.05 for two galaxies.
    predicted=HOOKS['reference_seconds']/500*(10/r['threads'])*1.05
    speed=round(r['seconds_per_step']/predicted,3)
    src=f"Benchmarked {time.strftime('%Y-%m-%d %H:%M')}: 100,000 particles, 2 galaxies, {r['threads']} threads, {r['seconds_per_step']:.2f} s/step (estimator predicts {predicted:.2f} s/step on this Mac)."
    _update_node(node_id,speed=speed,speed_source=src)
    BENCH[node_id]='done';return dict(speed=speed,speed_source=src,**r)

# ---------- location ----------
def location(p):
    loc=_read(Path(p)/'location.json',None)
    return loc or dict(node='local',plan=None,history=[],transfer=None)

def save_location(p,loc):HOOKS['atomic'](Path(p)/'location.json',loc)

def node_of(p):return location(p).get('node','local')

def is_remote(p):return node_of(p)!='local'

def remote_alive(jid):
    """True, False, or None when the node has not answered recently."""
    r=REMOTE.get(jid)
    if not r or not r.get('reachable'):return None
    if time.time()-r.get('synced_at',0)>120:return None
    if not r.get('alive') and time.time()-r.get('spawned_at',0)<25:return True   # worker still importing
    return bool(r.get('alive'))

# ---------- remote worker control ----------
def spawn_remote(p,threads):
    """Fresh start or hand-off target: replace the node's copy with the Mac's small files and checkpoint pair."""
    p=Path(p);node=get(node_of(p));d=jobdir(node,p.name)
    push(node,d,_push_list(p),pre=f'mkdir -p {d} && rm -f {d}/checkpoint-*.bin {d}/baryons-*.npz {d}/checkpoint.json {d}/worker.pid {d}/standby.json && ')
    _launch(p,node,threads)

def resume_remote(p,threads):
    """Resume in place from the node's own checkpoint (paused or interrupted there)."""
    p=Path(p);node=get(node_of(p));_launch(p,node,threads)

def _launch(p,node,threads):
    eng=ensure_engine(node);d=jobdir(node,p.name);py,pp=_pyenv(node)
    script=(f'set -e\ncd {d}\ntouch frames.bin\n'
        f'export OMP_NUM_THREADS={int(threads)} OMP_DYNAMIC=false OMP_WAIT_POLICY=PASSIVE OMP_PROC_BIND=false PYTHONPATH={pp}\n'
        'S=; command -v setsid >/dev/null 2>&1 && S=setsid\n'
        f'nohup $S {py} {eng}/worker.py "$PWD" >> worker.log 2>&1 < /dev/null &\necho started')
    ssh(node,script)
    REMOTE[p.name]=dict(REMOTE.get(p.name,{}),alive=True,reachable=True,spawned_at=time.time(),synced_at=time.time(),error=None)

def _push_list(p):
    """Small files plus only the checkpoint pair the pointer names. Old frames stay on the Mac."""
    files=[];ck=_read(p/'checkpoint.json',None)
    keep={ck.get('file'),ck.get('baryons')} if ck else set()
    for f in sorted(p.iterdir()):
        if not f.is_file() or f.name in PUSH_SKIP or f.name.endswith('.tmp') or f.name.startswith('.'):continue
        if (f.name.startswith('checkpoint-') or f.name.startswith('baryons-')) and f.name not in keep:continue
        files.append((f.name,f))
    return files

def send_control(p,action):
    node=get(node_of(p));d=jobdir(node,Path(p).name)
    body=json.dumps(dict(action=action,requested_at=time.time())).encode()
    ssh(node,f'cd {d} && cat > control.json.tmp && mv control.json.tmp control.json',data=body,timeout=20)

def kill_remote(p,wait=60):
    node=get(node_of(p));d=jobdir(node,Path(p).name);jid=Path(p).name
    script=(f'cd {d} 2>/dev/null || exit 0\npid=$(cat worker.pid 2>/dev/null)\n'
        f'[ -n "$pid" ] && ps -p "$pid" -o args= | grep -q {jid} && kill -TERM "$pid"\n'
        # A zombie (exited, not yet reaped by its parent) counts as stopped.
        'live() { [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && ! ps -p "$pid" -o stat= | grep -q Z; }\n'
        f'i=0; while live && [ $i -lt {wait*5} ]; do sleep .2; i=$((i+1)); done\n'
        'if live; then echo alive; else echo stopped; fi')
    out=ssh(node,script,timeout=wait+20).decode().strip()
    if out.endswith('alive'):raise NodeError(f"{node['label']}: worker did not stop within {wait} s")
    REMOTE.setdefault(jid,{})['alive']=False

def remove_remote(p):
    node=get(node_of(p));jid=Path(p).name
    kill_remote(p)
    ssh(node,f'rm -rf {jobdir(node,jid)}')
    REMOTE.pop(jid,None)

# ---------- sync ----------
def frame_size(p):
    meta=_read(Path(p)/'meta.json',{})
    return int(meta.get('n') or 0)*int(meta.get('bytes_per_particle') or 16)

def _fetch_frames(node,p,want_bytes,cap=FRAME_PULL_CAP):
    path=p/'frames.bin';path.touch(exist_ok=True);fs=frame_size(p)
    have=path.stat().st_size
    if fs and have%fs:
        with path.open('r+b') as f:f.truncate(have-have%fs)
        have-=have%fs
    if have>want_bytes:
        with path.open('r+b') as f:f.truncate(want_bytes)
        return
    if have==want_bytes:return
    count=want_bytes-have if cap is None else min(want_bytes-have,max(cap,fs))
    if fs:count-=count%fs
    d=jobdir(node,p.name)
    cmd=ssh_cmd(node)+['sh -c '+shlex.quote(f'cd {d} && tail -c +{have+1} frames.bin | head -c {count}')]
    with path.open('ab') as out:
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        got=0
        while True:
            chunk=proc.stdout.read(1<<20)
            if not chunk:break
            out.write(chunk);got+=len(chunk)
        out.flush()
        rc=proc.wait(600);err=proc.stderr.read()
    if fs and got%fs:
        with path.open('r+b') as f:f.truncate(path.stat().st_size-got%fs)
    if rc!=0 and not got:raise _err(node,err)

def sync(p,final=False):
    """Pull status, diagnostics and new frames for one remote job. Frames land before status advertises them."""
    p=Path(p);jid=p.name;node=get(node_of(p));stage=p/'.hub';d=jobdir(node,jid)
    pre=(f'pid=$(cat worker.pid 2>/dev/null); a=0\n'
         f'if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && ps -p "$pid" -o args= | grep -q {jid}; then a=1; fi\n'
         'echo $a > .hub-alive\n(wc -c < frames.bin) > .hub-size 2>/dev/null || echo 0 > .hub-size\n'
         'tail -c 32768 worker.log > .hub-log 2>/dev/null || :')
    state=REMOTE.setdefault(jid,{})
    try:
        got=pull(node,d,('.hub-alive','.hub-size','.hub-log')+SMALL_PULL,stage,pre=pre,timeout=120)
    except (NodeError,OSError) as e:
        state.update(reachable=False,error=str(e));return state
    alive=(stage/'.hub-alive').read_text().strip()=='1' if '.hub-alive' in got else False
    rsize=int((stage/'.hub-size').read_text().strip() or 0) if '.hub-size' in got else 0
    for name in ('meta.json','galaxy_index.bin','model_source.py','stellar_source.py','realistic_source.py','diagnostics.jsonl'):
        if name in got:shutil.copyfile(stage/name,p/(name+'.tmp'));(p/(name+'.tmp')).replace(p/name)
    fetch_error=None
    if 'status.json' in got:
        st=_read(stage/'status.json',{})
        fs=frame_size(p)
        if fs:
            want=min(int(st.get('frames') or 0),rsize//fs)*fs
            # Frames before this node's stint are the Mac's own. Right after a hand-off or pick-up the node's frames.bin is
            # briefly shorter than that (the worker has not re-extended it yet); never truncate below the stint's first frame.
            hist=location(p).get('history') or []
            floor=((hist[-1].get('start_frame') or 0)+1)*fs if hist and hist[-1].get('node')==node['id'] else 0
            if want<floor:want=min(floor,(p/'frames.bin').stat().st_size//fs*fs if (p/'frames.bin').exists() else 0)
            try:_fetch_frames(node,p,want,cap=None if final else FRAME_PULL_CAP)
            except (NodeError,OSError) as e:fetch_error=str(e)
            local=(p/'frames.bin').stat().st_size//fs if (p/'frames.bin').exists() else 0
            behind=int(st.get('frames') or 0)-local
            if behind>0:
                st['frames']=local;total=max(2,int(_read(p/'meta.json',{}).get('total_frames') or 2))
                st['progress']=min(st.get('progress') or 0,(local-1)/(total-1)) if local else 0
            st['frames_behind']=max(0,behind)
    # Update liveness before publishing status, so no reader sees a finished run whose worker still looks alive.
    # The start-up grace ends once the worker is seen, or once it has already finished (short runs can end between syncs).
    phase=(st if 'status.json' in got else _read(p/'status.json',{})).get('phase')
    state.update(alive=alive,reachable=True,synced_at=time.time(),error=fetch_error,node=node['id'])
    if alive or phase in ('complete','error'):state['spawned_at']=0
    if 'status.json' in got:HOOKS['atomic'](p/'status.json',st)
    return state

def pull_checkpoint(p):
    """Bring the committed checkpoint pair and every frame up to it onto the Mac."""
    p=Path(p);node=get(node_of(p));d=jobdir(node,p.name)
    got=pull(node,d,('checkpoint.json',),p/'.hub',timeout=60)
    if 'checkpoint.json' not in got:raise NodeError('The node has no checkpoint for this run yet.')
    ck=_read(p/'.hub'/'checkpoint.json',{})
    names=[n for n in (ck.get('file'),ck.get('baryons')) if n]
    got=pull(node,d,tuple(names)+('meta.json','status.json','diagnostics.jsonl','galaxy_index.bin'),p/'.hub',timeout=3600)
    missing=[n for n in names if n not in got]
    if missing:raise NodeError(f'Checkpoint files missing on the node: {missing}')
    for name in got:
        if name!='status.json':(p/'.hub'/name).replace(p/name)
    fs=frame_size(p);want=(int(ck['index'])+1)*fs
    _fetch_frames(node,p,want,cap=None)
    if (p/'frames.bin').stat().st_size!=want:raise NodeError('Frames up to the checkpoint did not arrive completely.')
    for old in list(p.glob('checkpoint-*.bin'))+list(p.glob('baryons-*.npz')):
        if old.name not in names:old.unlink()
    HOOKS['atomic'](p/'checkpoint.json',ck)
    st=dict(ck.get('status') or {});st.update(phase='paused',frames=int(ck['index'])+1);st.pop('frames_behind',None)
    HOOKS['atomic'](p/'status.json',st)
    return ck

# ---------- hand-off ----------
def _set_transfer(p,**fields):
    loc=location(p);t=dict(loc.get('transfer') or {});t.update(fields);loc['transfer']=t;save_location(p,loc);return loc

def _wait(pred,timeout,step=1.0):
    end=time.time()+timeout
    while time.time()<end:
        if pred():return True
        time.sleep(step)
    return False

def start_transfer(p,target):
    """Validate under the server LOCK, then run the move in a thread."""
    p=Path(p);loc=location(p);src=loc.get('node','local')
    if target==src:raise ValueError(f'This experiment already lives on {get(src)["label"]}.')
    get(target)
    if (loc.get('transfer') or {}).get('state') not in (None,'failed','done'):raise ValueError('A hand-off is already in progress.')
    st=_read(p/'status.json',{})
    if st.get('phase') in ('complete','error'):raise ValueError('Finished experiments stay where their frames are; nothing to hand off.')
    if st.get('phase')=='queued':raise ValueError('Queued experiments have not started. Remove and re-add with another node.')
    if HOOKS['busy'](target,p.name):raise ValueError(f'{get(target)["label"]} is already computing another experiment.')
    if target!='local':
        h=HEALTH.get(target) or probe(target)
        if not h.get('ready'):raise ValueError(h.get('error') or h.get('python_error') or f'{target} is not ready.')
    _set_transfer(p,to=target,source=src,state='pausing',started_at=time.time(),error=None)
    _bg('transfer:'+p.name,lambda:_transfer(p,src,target))

def _transfer(p,src,dst):
    jid=p.name;t0=time.time()
    try:
        status=lambda:_read(p/'status.json',{})
        armed_on=(location(p).get('standby') or {}).get('armed_on')
        if armed_on:disarm(p,armed_on,remove=armed_on!=dst)
        if src=='local':
            if HOOKS['alive_local'](jid):
                HOOKS['atomic'](p/'control.json',dict(action='pause',requested_at=time.time(),reason='hand-off'))
                if not _wait(lambda:status().get('phase') in FINAL_PHASES or not HOOKS['alive_local'](jid),6*3600):raise NodeError('Worker did not pause.')
                HOOKS['stop_local'](jid)
        else:
            node=get(src)
            send_control(p,'pause');HOOKS['atomic'](p/'control.json',dict(action='pause',requested_at=time.time(),reason='hand-off'))
            def paused():
                if not sync(p).get('reachable'):return False
                return status().get('phase') in FINAL_PHASES or remote_alive(jid) is False
            if not _wait(paused,6*3600,3):raise NodeError('Remote worker did not pause.')
            kill_remote(p)
            _set_transfer(p,state='copying')
            pull_checkpoint(p)
        st=status()
        if st.get('phase') in ('complete','error'):
            _set_transfer(p,state='done',note=f'Run reached {st.get("phase")} before the hand-off; left on {src}.');return
        ck=_read(p/'checkpoint.json',None)
        if not ck:raise NodeError('No checkpoint to hand off.')
        fs=frame_size(p);want=(int(ck['index'])+1)*fs
        if (p/'frames.bin').stat().st_size<want:raise NodeError('Local frames end before the checkpoint.')
        with (p/'frames.bin').open('r+b') as f:f.truncate(want)
        st.update(phase='paused',frames=int(ck['index'])+1);HOOKS['atomic'](p/'status.json',st)
        _set_transfer(p,state='starting')
        HOOKS['atomic'](p/'control.json',dict(action='run',requested_at=time.time(),reason='hand-off'))
        loc=location(p);hist=loc.get('history') or []
        if hist and hist[-1].get('ended_at') is None:hist[-1].update(ended_at=time.time(),end_frame=int(ck['index']))
        hist.append(dict(node=dst,started_at=time.time(),start_frame=int(ck['index']),ended_at=None))
        loc.update(node=dst,history=hist);save_location(p,loc)
        REMOTE.pop(jid,None)
        threads=int(_read(p/'config.json',{}).get('threads') or 1)
        if dst=='local':HOOKS['spawn_local'](p)
        else:
            cores=(HEALTH.get(dst) or {}).get('cores') or threads
            spawn_remote(p,min(threads,cores))
        _set_transfer(p,state='done',seconds=round(time.time()-t0,1),note=f'Handed off at frame {ck["index"]} from {get(src)["label"]} to {get(dst)["label"]}.')
    except Exception as e:
        _set_transfer(p,state='failed',error=str(e))

# ---------- multi-leg plans ----------
def plan_of(loc):
    """Plans are {legs:[{node,until}], leg}. Older runs stored {at,to,from,done}; read them as two legs."""
    plan=loc.get('plan')
    if not plan:return None
    if 'legs' in plan:return plan
    return dict(legs=[dict(node=plan['from'],until=plan['at']),dict(node=plan['to'],until=1.0)],leg=1 if plan.get('done') else 0,waiting=plan.get('waiting'))

def validate_legs(first,legs):
    """legs: [{node, until}] with until strictly increasing in (0,1); the last leg runs to the end."""
    if not isinstance(legs,list) or not 2<=len(legs)<=5:raise ValueError('A split needs 2 to 5 legs.')
    out=[];prev=0.0
    for i,leg in enumerate(legs):
        node=str(leg.get('node') or '');get(node)
        until=1.0 if i==len(legs)-1 else float(leg.get('until'))
        if i<len(legs)-1 and not (prev+.05<=until<=.95):raise ValueError('Each hand-off point must be at least 5% after the previous one and at most 95%.')
        if out and out[-1]['node']==node:raise ValueError('Consecutive legs must use different machines.')
        out.append(dict(node=node,until=until));prev=until
    if out[0]['node']!=first:raise ValueError('The first leg must be the starting machine.')
    return out

def _advance_plan(p,loc,st):
    plan=plan_of(loc)
    if not plan:return
    i=plan['leg'];legs=plan['legs']
    if i+1>=len(legs) or loc.get('node')!=legs[i]['node'] or st.get('phase')!='running' or (st.get('progress') or 0)<legs[i]['until']:return
    nxt=legs[i+1]['node']
    if HOOKS['busy'](nxt,p.name):
        # Keep computing here and retry each pass until the next machine frees up.
        if not plan.get('waiting'):plan['waiting']=f'{get(nxt)["label"]} is busy; this run keeps computing and hands off when it frees up.';loc['plan']=plan;save_location(p,loc)
        return
    plan['leg']=i+1;plan.pop('waiting',None);loc['plan']=plan;save_location(p,loc)
    try:start_transfer(p,nxt)
    except ValueError as e:_set_transfer(p,state='failed',to=nxt,error=f'Planned hand-off skipped: {e}')

# ---------- standby: an always-on node picks up a Mac run if the Mac goes quiet ----------
# The Mac copies its latest checkpoint pair to the node every few minutes and touches <runs>/hub-heartbeat every
# HEARTBEAT_EVERY seconds. A stdlib watchdog on the node resumes an armed shadow copy when the heartbeat is older
# than the grace period (lid closed, sleep, network loss). When the Mac is back it stops its own worker, discards
# its frames after the shadow checkpoint, and follows the node's copy (optionally handing it back).
HEARTBEAT_EVERY=float(os.environ.get('OBSERVATORY_HEARTBEAT_SECONDS',10))
STANDBY_GRACE=float(os.environ.get('OBSERVATORY_STANDBY_GRACE',90))
STANDBY_MIN_INTERVAL=float(os.environ.get('OBSERVATORY_STANDBY_MIN_INTERVAL',120))
WATCHDOG=r'''# Open Orbital standby watchdog: stdlib only. Started and restarted by the Mac hub over SSH.
import json,os,sys,time,glob,subprocess
RUNS,PY,PP,GRACE=sys.argv[1],sys.argv[2],sys.argv[3],float(sys.argv[4])
os.chdir(RUNS)
with open('standby-watchdog.pid','w') as f:f.write(str(os.getpid()))
def read(p,d):
    try:
        with open(p) as f:return json.load(f)
    except Exception:return d
def atomic(p,d):
    with open(p+'.tmp','w') as f:f.write(json.dumps(d))
    os.replace(p+'.tmp',p)
idle=None
while True:
    time.sleep(5)
    try:
        while os.waitpid(-1,os.WNOHANG)[0]:pass   # reap workers this watchdog started, so a stopped one is not a zombie
    except ChildProcessError:pass
    try:age=time.time()-os.stat('hub-heartbeat').st_mtime
    except FileNotFoundError:age=None
    armed=[(f,s) for f in glob.glob('jobs/*/standby.json') for s in [read(f,{})] if s.get('armed') and not s.get('taken')]
    if not armed:
        idle=idle or time.time()
        if time.time()-idle>600:break
        continue
    idle=None
    if age is None or age<GRACE:continue
    for f,s in armed:
        d=os.path.dirname(os.path.abspath(f));ck=read(os.path.join(d,'checkpoint.json'),None)
        if not ck:continue
        s.update(taken=True,taken_at=time.time(),heartbeat_age=round(age,1),index=ck.get('index'));atomic(f,s)
        atomic(os.path.join(d,'control.json'),dict(action='run',requested_at=time.time(),reason='standby pick-up'))
        open(os.path.join(d,'frames.bin'),'ab').close()
        env=dict(os.environ,OMP_NUM_THREADS=str(s['threads']),OMP_DYNAMIC='false',OMP_WAIT_POLICY='PASSIVE',OMP_PROC_BIND='false',PYTHONPATH=PP)
        with open(os.path.join(d,'worker.log'),'ab') as log:
            subprocess.Popen([PY,os.path.join(s['engine'],'worker.py'),d],stdout=log,stderr=log,stdin=subprocess.DEVNULL,env=env,start_new_session=True)
try:os.remove('standby-watchdog.pid')
except FileNotFoundError:pass
'''

def standby_interval(p):
    """Seconds between shadow copies: 2 s per MB of checkpoint pair, clamped to 2–30 minutes (floor overridable for tests)."""
    ck=_read(p/'checkpoint.json',{});size=sum((p/n).stat().st_size for n in (ck.get('file'),ck.get('baryons')) if n and (p/n).exists())
    return max(STANDBY_MIN_INTERVAL,min(1800,2*size/1e6))

def default_standby(exclude=()):
    """Fastest always-on node that is ready (lowest measured speed factor)."""
    ready=[n for n in registry() if n.get('always_on') and n['id'] not in exclude and (HEALTH.get(n['id']) or {}).get('ready')]
    return min(ready,key=lambda n:n.get('speed') or 99)['id'] if ready else None

def push_shadow(p,node_id):
    p=Path(p);node=get(node_id);jid=p.name;d=jobdir(node,jid);runs=rpath(node,node['runs'])
    ck=_read(p/'checkpoint.json',None)
    if not ck:return
    eng=ensure_engine(node);py,pp=_pyenv(node)
    push(node,runs,[('standby_watchdog.py',WATCHDOG.encode())])
    threads=int(_read(p/'config.json',{}).get('threads') or 1);cores=(HEALTH.get(node_id) or {}).get('cores') or threads
    engine=ssh(node,f'cd {eng} && pwd').decode().strip()
    meta=dict(armed=True,taken=False,index=int(ck['index']),threads=min(threads,cores),engine=engine,pushed_at=time.time(),grace=STANDBY_GRACE)
    # Stage then swap, so the node never holds a checkpoint.json that points at a half-copied pair.
    # Never overwrite a copy the node has already picked up.
    taken=f'if grep -q \'"taken": true\' {d}/standby.json 2>/dev/null; then echo TAKEN; exit 0; fi\n'
    push(node,d+'.staging',_push_list(p),pre=taken.replace('\n','; ')+f'rm -rf {d}.staging && ')
    out=ssh(node,taken+f'cat > {d}.staging/standby.json\nrm -rf {d}.prev; [ -d {d} ] && mv {d} {d}.prev; mv {d}.staging {d} && rm -rf {d}.prev && echo OK',
            data=json.dumps(meta).encode()).decode().strip()
    if out.endswith('TAKEN'):return
    loc=location(p);loc['standby']=dict(loc.get('standby') or {},armed_on=node_id,pushed_at=meta['pushed_at'],index=meta['index'],error=None);save_location(p,loc)

def disarm(p,node_id,remove=False):
    p=Path(p);node=get(node_id);d=jobdir(node,p.name)
    if remove:ssh(node,f'if grep -q \'"taken": true\' {d}/standby.json 2>/dev/null; then exit 0; fi; rm -rf {d} {d}.staging')
    else:ssh(node,f'[ -f {d}/standby.json ] && sed -i \'s/"armed": true/"armed": false/\' {d}/standby.json; true')
    loc=location(p)
    if (loc.get('standby') or {}).get('armed_on')==node_id:loc['standby'].pop('armed_on',None);save_location(p,loc)

def heartbeat(node_id):
    """Touch the heartbeat, keep the watchdog alive, and report copies the node has picked up."""
    node=get(node_id);runs=rpath(node,node['runs']);py,pp=_pyenv(node)
    script=(f'cd {runs} || exit 3\ntouch hub-heartbeat\n'
        'pid=$(cat standby-watchdog.pid 2>/dev/null)\n'
        f'if [ -f standby_watchdog.py ] && ! {{ [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; }}; then nohup {py} standby_watchdog.py "$PWD" {py} {pp} {STANDBY_GRACE} >> standby-watchdog.log 2>&1 < /dev/null & fi\n'
        'for f in jobs/*/standby.json; do [ -f "$f" ] && grep -q \'"taken": true\' "$f" && echo "TAKEN $(basename $(dirname "$f")) $(tr -d \'\\n\' < "$f")"; done; true')
    taken={}
    for line in ssh(node,script,timeout=30).decode(errors='replace').splitlines():
        if line.startswith('TAKEN '):
            _,jid,body=line.split(' ',2)
            try:taken[jid]=json.loads(body)
            except ValueError:pass
    return taken

def adopt_pickup(p,node_id,info):
    """The node resumed this run while the Mac was away. Stop the Mac's worker and follow the node's copy."""
    p=Path(p);jid=p.name
    HOOKS['stop_local'](jid)
    idx=int(info.get('index') or 0);fs=frame_size(p)
    if fs and (p/'frames.bin').exists() and (p/'frames.bin').stat().st_size>(idx+1)*fs:
        with (p/'frames.bin').open('r+b') as f:f.truncate((idx+1)*fs)
    st=_read(p/'status.json',{});st.update(phase='running',frames=idx+1);st.pop('error',None);HOOKS['atomic'](p/'status.json',st)
    loc=location(p);hist=loc.get('history') or []
    if hist and hist[-1].get('ended_at') is None:hist[-1].update(ended_at=info.get('taken_at'),end_frame=idx)
    hist.append(dict(node=node_id,started_at=info.get('taken_at'),start_frame=idx,ended_at=None,reason='standby pick-up'))
    sb=dict(loc.get('standby') or {},taken_at=info.get('taken_at'),index=idx,heartbeat_age=info.get('heartbeat_age'))
    sb['note']=f'{get(node_id)["label"]} picked this run up at frame {idx} after this Mac was silent for {info.get("heartbeat_age")} s.'
    sb.pop('armed_on',None)
    loc.update(node=node_id,history=hist,standby=sb,return_pending=bool(sb.get('return_on_wake')),synced_complete=False);save_location(p,loc)
    REMOTE[jid]=dict(alive=True,reachable=True,synced_at=time.time(),spawned_at=time.time(),error=None)

def _standby_pass(p,loc,st,now):
    """Runs on this Mac: keep the shadow copy fresh while computing, disarm otherwise. Returns a node needing heartbeats."""
    sb=loc.get('standby') or {};jid=p.name;node_id=sb.get('node');armed_on=sb.get('armed_on')
    if loc.get('node','local')!='local' or running('shadow:'+jid):return armed_on
    ctl=_read(p/'control.json',{}).get('action');phase=st.get('phase')
    wanted=bool(node_id) and phase in ('running','initializing','pausing') and ctl!='pause' and (p/'checkpoint.json').exists()
    if wanted:
        ck=_read(p/'checkpoint.json',{})
        if armed_on!=node_id or (ck.get('index')!=sb.get('index') and now-sb.get('pushed_at',0)>=standby_interval(p)):
            def go(p=p,node_id=node_id,old=armed_on):
                try:
                    if old and old!=node_id:disarm(p,old,True)
                    push_shadow(p,node_id)
                except Exception as e:
                    l=location(p);l['standby']=dict(l.get('standby') or {},error=str(e));save_location(p,l)
            _bg('shadow:'+jid,go)
        return node_id
    if armed_on:_bg('shadow:'+jid,lambda p=p,n=armed_on,f=phase in ('complete','error'):_safe_disarm(p,n,f))
    return armed_on

def _safe_disarm(p,node_id,remove):
    try:disarm(p,node_id,remove)
    except Exception:pass

def set_standby(p,node_id,return_on_wake=True):
    p=Path(p);loc=location(p)
    if node_id:
        n=get(node_id)
        if node_id=='local':raise ValueError('Standby needs another machine.')
        if not (HEALTH.get(node_id) or {}).get('ready'):raise ValueError(f'{n["label"]} is not ready.')
    old=dict(loc.get('standby') or {})
    loc['standby']=dict(old,node=node_id,return_on_wake=bool(return_on_wake));save_location(p,loc)
    return loc['standby']

# ---------- background loop ----------
def _bg(key,fn):
    with _TLOCK:
        th=_THREADS.get(key)
        if th and th.is_alive():return False
        th=threading.Thread(target=fn,daemon=True,name=key);_THREADS[key]=th;th.start();return True

def running(key):
    th=_THREADS.get(key);return bool(th and th.is_alive())

def loop(stop,job_dirs):
    """Probe nodes, sync remote jobs, and fire planned hand-offs. Never holds the server LOCK."""
    last_probe={};last_sync={};last_beat={}
    while not stop.wait(1.0):
        now=time.time();standby_jobs={}
        try:nodes=registry()
        except Exception:nodes=[]
        for n in nodes:
            if now-last_probe.get(n['id'],0)>45:
                last_probe[n['id']]=now;_bg('probe:'+n['id'],lambda i=n['id']:probe(i))
        for p in job_dirs():
            try:
                loc=location(p);st=_read(p/'status.json',{});jid=p.name
                t=(loc.get('transfer') or {}).get('state')
                if t in ('pausing','copying','starting') or running('transfer:'+jid):continue
                if loc.get('node','local')!='local' and not loc.get('synced_complete'):
                    phase=st.get('phase');active=phase in ('running','initializing','pausing')
                    interval=3 if active or st.get('frames_behind') else 30
                    if now-last_sync.get(jid,0)>=interval:
                        last_sync[jid]=now
                        def job_sync(p=p):
                            s=sync(p)
                            st2=_read(p/'status.json',{})
                            if s.get('reachable') and st2.get('phase') in ('complete','error') and not st2.get('frames_behind') and not s.get('alive'):
                                l2=location(p);l2['synced_complete']=True;save_location(p,l2)
                        _bg('sync:'+jid,job_sync)
                _advance_plan(p,loc,st)
                beat=_standby_pass(p,loc,st,now)
                if beat:standby_jobs.setdefault(beat,[]).append(p)
                if loc.get('return_pending') and loc.get('node','local')!='local' and st.get('phase')=='running' and (REMOTE.get(jid) or {}).get('alive') and not (REMOTE.get(jid) or {}).get('spawned_at'):
                    if not HOOKS['busy']('local',jid):
                        loc['return_pending']=False;save_location(p,loc)
                        try:start_transfer(p,'local')
                        except ValueError as e:_set_transfer(p,state='failed',to='local',error=f'Return to this Mac skipped: {e}')
            except Exception:
                continue
        for node_id,plist in standby_jobs.items():
            if now-last_beat.get(node_id,0)>=HEARTBEAT_EVERY:
                last_beat[node_id]=now
                def beat(node_id=node_id,plist=plist):
                    try:taken=heartbeat(node_id)
                    except Exception:return
                    for p in plist:
                        sb=location(p).get('standby') or {}
                        if p.name in taken and location(p).get('node','local')=='local' and sb.get('armed_on')==node_id:adopt_pickup(p,node_id,taken[p.name])
                _bg('beat:'+node_id,beat)
