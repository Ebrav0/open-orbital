import psutil,time,subprocess,os
p=next(p for p in psutil.process_iter(['cmdline']) if p.info['cmdline'] and p.info['cmdline'][-1]=='outputs/gravity_benchmark.py')
while p.is_running() and p.status()!=psutil.STATUS_ZOMBIE:time.sleep(5)
env=os.environ.copy();env['CFLAGS']='-Xpreprocessor -fopenmp -DOPENMP -I/opt/homebrew/opt/libomp/include';env['LDFLAGS']='-L/opt/homebrew/opt/libomp/lib -lomp -Wl,-rpath,/opt/homebrew/opt/libomp/lib'
subprocess.run(['work/venv/bin/pip','install','--no-deps','--target','work/openmp','./work/source/rebound-5.1.1'],env=env,check=True)
env=os.environ.copy();env['PYTHONPATH']=os.path.abspath('work/openmp');env['OMP_WAIT_POLICY']='PASSIVE'
for threads in [1,4,8,10,14]:
    subprocess.run(['work/venv/bin/python','outputs/openmp_benchmark.py',str(threads)],env=env,check=True)
print('OPENMP_DONE',flush=True)
