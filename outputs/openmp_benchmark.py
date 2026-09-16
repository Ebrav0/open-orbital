"""Supplemental single-simulation multicore timings, using a separately built REBOUND."""
import sys,ctypes,json
import gravity_benchmark as b
threads=int(sys.argv[1]);lib=ctypes.CDLL('/opt/homebrew/opt/libomp/lib/libomp.dylib');lib.omp_set_num_threads(threads)
rows=[]
for n in [10000,100000,300000]:
    r=b.speed(n,'tree');r['threads']=threads;rows.append(r);print(json.dumps(r),flush=True)
if threads==8:
    r=b.speed(1000000,'tree');r['threads']=threads;rows.append(r);print(json.dumps(r),flush=True)
if threads==8:
    r=b.speed(100000,'tree',theta=.3);r['threads']=threads;rows.append(r);print(json.dumps(r),flush=True)
data=dict(threads=threads,library=b.rebound.clibrebound._name,rows=rows)
if threads==8:data['accuracy']=b.accuracy()
(b.OUT/f'openmp_{threads}.json').write_text(json.dumps(data,indent=2))
