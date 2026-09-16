import time,psutil,json,subprocess
from pathlib import Path
p=next(p for p in psutil.process_iter(['cmdline']) if p.info['cmdline'] and p.info['cmdline'][-1]=='outputs/gravity_benchmark.py')
out=Path('outputs/resource_samples.jsonl')
while p.is_running() and p.status()!=psutil.STATUS_ZOMBIE:
    children=p.children(recursive=True)
    rss=sum(x.memory_info().rss for x in children if x.is_running())
    row=dict(time=time.time(),cpu_percent=psutil.cpu_percent(interval=1),load=psutil.getloadavg(),benchmark_tree_rss_mib=rss/2**20,available_ram_gib=psutil.virtual_memory().available/2**30,swap_used_gib=psutil.swap_memory().used/2**30,thermal=subprocess.run(['pmset','-g','therm'],capture_output=True,text=True).stdout)
    with out.open('a') as f:f.write(json.dumps(row)+'\n')
    time.sleep(19)
