import urllib.request,json,subprocess,os,time,plistlib
from pathlib import Path
base='http://127.0.0.1:8766';jid='67be855d5342'
def api(path,data=None):
 req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data else None,headers={'Content-Type':'application/json'})
 return json.load(urllib.request.urlopen(req,timeout=3))
api('/api/jobs/'+jid+'/control',{'action':'pause'})
for _ in range(300):
 j=api('/api/jobs/'+jid)
 if j['status']['phase']=='paused':break
 time.sleep(.2)
else:raise RuntimeError('Pause failed')
print('Checkpoint saved at',j['status']['frames'],'frames',flush=True)
p=Path.home()/'Library/LaunchAgents/com.openorbital.observatory.plist'
Path('work/launchagent-before-cpu-fix.log').write_bytes(p.read_bytes())
d=plistlib.loads(p.read_bytes());d['ProcessType']='Interactive';p.write_bytes(plistlib.dumps(d))
subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/com.openorbital.observatory'],check=True)
subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(p)],check=True)
for _ in range(150):
 try:api('/api/system');break
 except Exception:time.sleep(.2)
else:raise RuntimeError('Service not ready')
api('/api/jobs/'+jid+'/control',{'action':'run'})
print('Resumed',flush=True)
