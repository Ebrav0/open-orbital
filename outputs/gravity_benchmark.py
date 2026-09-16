"""Reproducible CPU gravity benchmark. Run with the task's work/venv Python.
All particles gravitate; no GPU, rendering, gas, or stellar evolution.
"""
import os
os.environ['OMP_NUM_THREADS']='1'
import time,json,math,platform,subprocess,statistics,resource
from pathlib import Path
import numpy as np
import psutil,rebound
from concurrent.futures import ProcessPoolExecutor
OUT=Path(__file__).parent

def cloud(n,solver='tree',theta=.5,dt=1e-5):
    rng=np.random.default_rng(731)
    pos=rng.normal(size=(n,3)); pos/=np.linalg.norm(pos,axis=1)[:,None]
    pos*=rng.random(n)[:,None]**(1/3)
    vel=rng.normal(0,.2,(n,3))
    s=rebound.Simulation();s.G=1;s.dt=dt;s.integrator='leapfrog'
    s.softening=.02;s.root_size=16;s.N_root_x=1;s.N_root_y=1;s.N_root_z=1
    s.gravity=solver;s.opening_angle2=theta**2
    for p,v in zip(pos,vel):s.add(m=1/n,x=p[0],y=p[1],z=p[2],vx=v[0],vy=v[1],vz=v[2])
    s.move_to_com()
    return s

def state(s):
    return np.array([[p.x,p.y,p.z,p.vx,p.vy,p.vz] for p in s.particles])

def energy(s):
    q=state(s); n=len(q); m=1/n
    e=.5*m*np.sum(q[:,3:]**2)
    for i in range(n-1):e-=m*m*np.sum(1/np.sqrt(np.sum((q[i+1:,:3]-q[i,:3])**2,axis=1)+s.softening**2))
    return float(e)

def accuracy():
    s=rebound.Simulation();s.add(m=1);s.add(m=1e-3,a=1);s.move_to_com();s.integrator='ias15'
    e=s.energy();period=2*math.pi/math.sqrt(1.001);s.integrate(100*period)
    orbit_error=abs(s.energy()/e-1)
    base=cloud(512,'basic',dt=1e-6); tree=cloud(512,'tree',dt=1e-6)
    v0=state(base)[:,3:];base.steps(1);tree.steps(1)
    a=(state(base)[:,3:]-v0)/base.dt;b=(state(tree)[:,3:]-v0)/tree.dt
    err=np.linalg.norm(a-b,axis=1)/np.maximum(np.linalg.norm(a,axis=1),1e-12)
    conv=[]
    for solver,theta,dt in [('basic',.5,.002),('basic',.5,.001),('tree',.5,.002),('tree',.3,.002)]:
        s=cloud(512,solver,theta,dt);e=energy(s);s.steps(round(.5/dt))
        conv.append(dict(solver=solver,theta=theta,dt=dt,relative_energy_error=abs(energy(s)/e-1),final=state(s)))
    ref=conv[1]['final'];
    for c in conv:
        c['position_rms_vs_direct_half_dt']=float(np.sqrt(np.mean((c.pop('final')[:,:3]-ref[:,:3])**2)))
    return dict(two_body_100_orbits_relative_energy_error=orbit_error,tree_force_relative_median=float(np.median(err)),tree_force_relative_p95=float(np.percentile(err,95)),tree_force_relative_max=float(max(err)),cloud_checks=conv)

def speed(n,solver,theta=.5):
    init=time.perf_counter();s=cloud(n,solver,theta);setup=time.perf_counter()-init
    t=time.perf_counter();s.steps(1);cold=time.perf_counter()-t
    count=max(1,min(100,int(.6/max(cold,1e-6))))
    times=[]; cpus=[]
    for _ in range(3):
        c=s.copy();t=time.perf_counter();cpu=time.process_time();c.steps(count)
        cpus.append(time.process_time()-cpu);times.append(time.perf_counter()-t)
    return dict(n=n,solver=solver,theta=theta,setup_s=setup,cold_step_s=cold,steps_per_repeat=count,repeat_s=times,seconds_per_step=statistics.median(times)/count,cpu_wall_ratio=sum(cpus)/sum(times),peak_process_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/2**20)

def worker(args):
    n,start,duration=args;s=cloud(n);s.steps(1)
    while time.monotonic()<start:time.sleep(.01)
    records=[];total=0;cpu=time.process_time();t=time.monotonic();end=start+duration
    bucket=t;steps=0
    while time.monotonic()<end:
        # Repeated identical short trajectories avoid changing density skewing throughput.
        c=s.copy();c.steps(8);steps+=8;total+=8
        now=time.monotonic()
        if now-bucket>=10:
            records.append(dict(elapsed=now-start,steps=steps,seconds=now-bucket));bucket=now;steps=0
    now=time.monotonic()
    if steps:records.append(dict(elapsed=now-start,steps=steps,seconds=now-bucket))
    return dict(steps=total,wall_s=now-t,cpu_s=time.process_time()-cpu,buckets=records,peak_process_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/2**20)

def parallel(workers,duration):
    with ProcessPoolExecutor(max_workers=workers) as pool:
        start=time.monotonic()+4
        results=list(pool.map(worker,[(10000,start,duration)]*workers))
    wall=max(r['wall_s'] for r in results)
    return dict(workers=workers,duration_s=duration,aggregate_steps_per_s=sum(r['steps'] for r in results)/wall,effective_cpu_cores=sum(r['cpu_s'] for r in results)/wall,results=results)

def save(data):
    (OUT/'benchmark_results.json').write_text(json.dumps(data,indent=2))

def main():
    data=dict(timestamp=time.strftime('%Y-%m-%d %H:%M:%S %z'),hardware=dict(cpu=subprocess.check_output(['sysctl','-n','machdep.cpu.brand_string'],text=True).strip(),cores=os.cpu_count(),ram_gib=psutil.virtual_memory().total/2**30,platform=platform.platform(),load=os.getloadavg(),available_ram_gib=psutil.virtual_memory().available/2**30),versions=dict(python=platform.python_version(),rebound=rebound.__version__,numpy=np.__version__),settings=dict(seed=731,G=1,mass=1,radius=1,softening=.02,theta=.5,dt=1e-5,integrator='leapfrog',description='Uniform sphere, Gaussian velocities sigma=0.2; synthetic softened self-gravity workload, not an equilibrium galaxy.'))
    data['accuracy']=accuracy();save(data);print('ACCURACY',json.dumps(data['accuracy']),flush=True)
    data['scaling']=[]
    for solver,ns in [('basic',[1000,3000,10000]),('tree',[1000,3000,10000,30000,100000,300000])]:
        for n in ns:
            with ProcessPoolExecutor(max_workers=1) as p:r=p.submit(speed,n,solver).result()
            data['scaling'].append(r);save(data);print('SCALING',json.dumps(r),flush=True)
    data['parallel']=[]
    for workers in [1,4,8,10,14]:
        r=parallel(workers,15);data['parallel'].append(r);save(data);print('PARALLEL',workers,r['aggregate_steps_per_s'],r['effective_cpu_cores'],flush=True)
    best=max(data['parallel'],key=lambda r:r['aggregate_steps_per_s'])['workers']
    print('SUSTAINED_START',best,600,flush=True)
    data['sustained']=parallel(best,600);save(data)
    print('DONE',data['sustained']['aggregate_steps_per_s'],flush=True)
if __name__=='__main__':main()
