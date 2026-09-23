"""Regression: a 14-thread request must not be reduced to the P-core count.
Run with the project's OpenMP PYTHONPATH. Does not start a simulation.
"""
import ctypes,ctypes.util,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from physics import effective_threads,set_threads
requested=min(14,os.cpu_count() or 1)
assert effective_threads(requested)==requested
assert set_threads(requested)==requested
omp=ctypes.CDLL(ctypes.util.find_library('gomp') if sys.platform.startswith('linux') else '/opt/homebrew/opt/libomp/lib/libomp.dylib')
assert omp.omp_get_max_threads()==requested
assert os.environ['OMP_PROC_BIND']=='false'
print(f'Thread request honored: {requested}; OpenMP maximum team: {requested}; binding disabled.')
