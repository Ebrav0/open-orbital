from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
P=Path(__file__).parent
d=[json.loads((P/f'openmp_{t}.json').read_text()) for t in [1,4,8,10,14]]
rows=[r for run in d for r in run['rows']]
text='\n## Supplemental: one simulation across multiple CPU cores\n\nA second REBOUND 5.1.1 build enables OpenMP using Apple Clang and the existing Homebrew libomp runtime. It is isolated under work/openmp; the original serial environment is preserved. OMP_WAIT_POLICY=PASSIVE. Same seeded particles, softening, integrator and timestep as the original table. Three timed batches per case, after warm-up. Compilation explicitly selects the installed macOS 26.5 SDK to avoid a local linker incompatibility with SDK 27.0. Supplemental memory values are process high-water marks and can include an earlier, larger case within that same process. These are short scaling measurements after the sustained ensemble test, not a ten-minute threaded test.\n\n| Particles | Threads | Theta | ms / step | Effective CPU cores | Peak process MiB |\n|---:|---:|---:|---:|---:|---:|\n'
for r in rows:text+=f"| {r['n']:,} | {r['threads']} | {r['theta']} | {r['seconds_per_step']*1000:.2f} | {r['cpu_wall_ratio']:.2f} | {r['peak_process_mib']:.1f} |\n"
one=next(r for r in rows if r['n']==1000000)
best=min((r for r in rows if r['n']==100000 and r['theta']==.5),key=lambda r:r['seconds_per_step'])
text+=f"\nOne million mutually gravitating particles was actually tested: **{one['seconds_per_step']:.3f} seconds per step** with eight threads. Multiplying that short measurement by 10,000 gives **{one['seconds_per_step']*10000/3600:.2f} hours**; this is a projection, not an evolved galaxy or a completed long run. Best measured 100,000-particle thread count: **{best['threads']}**, at **{best['seconds_per_step']*1000:.1f} ms/step**.\n\n"
text+='The eight-thread accuracy checks are saved in openmp_8.json and checked against the original force-error result. More threads need not be faster: shared-memory overhead, serial tree construction, core speeds and other workloads all affect scaling.\n\n![Single simulation thread scaling](threaded_charts.png)\n'
p=P/'BENCHMARK_REPORT.md';s=p.read_text().split('\n## Supplemental: one simulation across multiple CPU cores')[0];s=s.replace('One million remains unmeasured unless a supplemental result is included below.','The supplemental tests below also measure one million particles with a separate threaded build.')
s=s.replace('The tested engine uses approximately one CPU core per simulation. Multiple processes use the CPU across independent experiments. These measurements do not establish multicore acceleration of one large galaxy.','The initial binary uses approximately one CPU core per simulation. Multiple processes use the CPU across independent experiments. The supplemental OpenMP build below additionally measures multicore acceleration within one simulation.')
p.write_text(s+text)
plt.style.use('dark_background');fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained');fig.patch.set_facecolor('#101622')
for ax in axes:ax.set_facecolor('#101622');ax.grid(alpha=.15)
for n,color in [(10000,'#ffaf70'),(100000,'#60d7d0'),(300000,'#b89bff')]:
    rs=[r for r in rows if r['n']==n and r['theta']==.5]
    axes[0].plot([r['threads'] for r in rs],[r['seconds_per_step'] for r in rs],'o-',label=f'{n:,} particles',color=color)
axes[0].set(yscale='log',xlabel='Threads in one simulation',ylabel='Seconds per physics step',title='Measured multicore scaling');axes[0].legend();axes[0].set_xticks([1,4,8,10,14])
rs=[r for r in rows if r['threads']==8 and r['theta']==.5]
axes[1].loglog([r['n'] for r in rs],[r['seconds_per_step'] for r in rs],'o-',color='#60d7d0')
for r in rs:axes[1].annotate(f"{r['seconds_per_step']:.3f}s",(r['n'],r['seconds_per_step']),xytext=(0,9),textcoords='offset points',ha='center')
axes[1].set(xlabel='Mutually gravitating particles',ylabel='Seconds per physics step',title='Eight threads: up to one million particles');axes[1].margins(.2)
fig.suptitle('One gravitational simulation · Apple M4 Pro · CPU only',fontsize=16);fig.savefig(P/'threaded_charts.png',dpi=180)
print(json.dumps(dict(best_100k=best,million=one),indent=2))
