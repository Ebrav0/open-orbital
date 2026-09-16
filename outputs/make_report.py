"""Generate report and figure from measured benchmark_results.json."""
import json,math,statistics
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
P=Path(__file__).parent
d=json.loads((P/'benchmark_results.json').read_text());a=d['accuracy'];s=d['scaling'];par=d['parallel'];sust=d['sustained']
plt.style.use('dark_background')
fig,axes=plt.subplots(2,2,figsize=(13,8.5),layout='constrained')
fig.patch.set_facecolor('#101622')
for ax in axes.flat:
    ax.set_facecolor('#101622');ax.grid(alpha=.15)
for solver,color,label in [('basic','#ffaf70','Direct pairwise'),('tree','#60d7d0','Tree, theta = 0.5')]:
    rows=[r for r in s if r['solver']==solver]
    axes[0,0].loglog([r['n'] for r in rows],[r['seconds_per_step'] for r in rows],'o-',color=color,label=label)
axes[0,0].set(xlabel='Mutually gravitating particles',ylabel='Seconds per physics step',title='Particle scaling: measured, single worker');axes[0,0].legend()
workers=[r['workers'] for r in par];rates=[r['aggregate_steps_per_s'] for r in par]
axes[0,1].bar([str(w) for w in workers],rates,color='#60d7d0')
axes[0,1].set(xlabel='Independent CPU workers',ylabel='Aggregate physics steps / second',title='Parallel 10,000-particle experiments')
for i,v in enumerate(rates):axes[0,1].text(i,v+2,f'{v:.1f}',ha='center',fontsize=9)
# Common 30-second windows, apportioning each recorded bucket by overlap.
bins=np.arange(0,601,30);tot=np.zeros(len(bins)-1)
for r in sust['results']:
    for b in r['buckets']:
        end=b['elapsed'];start=end-b['seconds'];rate=b['steps']/b['seconds']
        for j in range(len(tot)):
            overlap=max(0,min(end,bins[j+1])-max(start,bins[j]));tot[j]+=rate*overlap/30
axes[1,0].plot((bins[:-1]+15)/60,tot,'o-',color='#b89bff')
axes[1,0].set(xlabel='Elapsed minutes',ylabel='Aggregate physics steps / second',title=f'10-minute sustained test: {sust["workers"]} workers',ylim=(0,max(tot)*1.2))
checks=a['cloud_checks'];axes[1,1].bar(['Direct\ndt .002','Direct\ndt .001','Tree .5\ndt .002','Tree .3\ndt .002'],[r['relative_energy_error'] for r in checks],color=['#ffaf70','#ffaf70','#60d7d0','#60d7d0'])
axes[1,1].set(yscale='log',ylabel='Absolute relative energy change',title='Accuracy: 512 particles, 0.5 model time units')
fig.suptitle('Gravity on Apple M4 Pro · 14 CPU cores · 24 GiB RAM',fontsize=18)
fig.savefig(P/'benchmark_charts.png',dpi=180);plt.close(fig)

def duration(sec):
    if sec<60:return f'{sec:.1f} sec'
    if sec<3600:return f'{sec/60:.1f} min'
    return f'{sec/3600:.2f} hr'
rows=[]
for r in s:
    rows.append(f"| {r['n']:,} | {r['solver']} | {r['seconds_per_step']*1000:.2f} | {1/r['seconds_per_step']:.2f} | {duration(r['seconds_per_step']*10000)} | {r['peak_process_mib']:.1f} |")
prows=[]
for r in par:
    prows.append(f"| {r['workers']} | {r['aggregate_steps_per_s']:.2f} | {r['aggregate_steps_per_s']/par[0]['aggregate_steps_per_s']:.2f}x | {r['effective_cpu_cores']:.2f} |")
resources=[json.loads(l) for l in (P/'resource_samples.jsonl').read_text().splitlines()] if (P/'resource_samples.jsonl').exists() else []
first=float(np.mean(tot[:4]));last=float(np.mean(tot[-4:]));rate=sust['aggregate_steps_per_s']
text=f'''# Gravity benchmark — Apple M4 Pro

Measured {d['timestamp']}. CPU-only REBOUND {d['versions']['rebound']}, Python {d['versions']['python']}, NumPy {d['versions']['numpy']}. Hardware: 10 performance + 4 efficiency cores, 24 GiB RAM. Connected to AC power. Other applications remained running; initial load averages: {d['hardware']['load']}.

## Findings

- This machine can compute 300,000 mutually gravitating particles with the tree solver; this is an actual measured workload, not a particle-count extrapolation.
- The tested engine uses approximately one CPU core per simulation. Multiple processes use the CPU across independent experiments. These measurements do not establish multicore acceleration of one large galaxy.
- Best short parallel result: {max(par,key=lambda x:x['aggregate_steps_per_s'])['workers']} workers. The ten-minute run achieved **{rate:.2f} aggregate steps/s**, using **{sust['effective_cpu_cores']:.2f} CPU cores on average**.
- At that sustained rate, eight hours would yield about **{rate*28800/10000:.0f} jobs of 10,000 steps each**, for the identical 10,000-particle workload. This is a throughput projection, not a completed overnight run or validated merger duration.

![Measured scaling and accuracy](benchmark_charts.png)

## Particle scaling

Median of three timed batches after one warm-up step; setup and state copying excluded. Every particle contributes gravity. Peak memory includes the Python process, initial arrays and temporary simulation copies; it is not an isolated particle-buffer size. Large cases use only one step per timed batch, so their long-run performance remains unverified.

| Particles | Solver | ms / step | Steps / sec | Projected 10,000 steps | Peak process MiB |
|---:|---|---:|---:|---:|---:|
{chr(10).join(rows)}

The 10,000-step column multiplies measured median time by 10,000. Density changes, close encounters, accuracy settings and output can change the cost. No render or snapshot-writing cost is included.

## Parallel experiments

Independent 10,000-particle tree simulations, 15 seconds per worker-count trial. Workers are started before a shared deadline. Throughput includes copying the state and evolving an eight-step segment repeatedly. This keeps the density and computational workload comparable throughout the test. It tests sustained execution of repeated segments, not the physical evolution of one system for ten minutes.

| Workers | Aggregate steps/s | Speedup vs 1 | CPU cores used |
|---:|---:|---:|---:|
{chr(10).join(prows)}

## Ten-minute sustained test

- Workers: {sust['workers']}.
- Total completed steps across workers: {sum(r['steps'] for r in sust['results']):,}.
- Aggregate rate: {rate:.2f} steps/s.
- First two minutes: {first:.2f} steps/s; final two minutes: {last:.2f} steps/s ({(last/first-1)*100:+.1f}%). Rates use overlap-weighted 30-second bins.
- Peak sampled sum of child-process RSS: {max((r['benchmark_tree_rss_mib'] for r in resources),default=0):.1f} MiB. Summed RSS can double-count shared pages.
- Minimum sampled available system RAM: {min((r['available_ram_gib'] for r in resources),default=0):.2f} GiB.
- macOS thermal-status output is saved in resource_samples.jsonl. It does not provide CPU temperatures or prove the absence of throttling. Throughput is the primary sustained-performance evidence.

## Accuracy checks

1. Two-body circular orbit, IAS15, 100 orbital periods: relative energy change **{a['two_body_100_orbits_relative_energy_error']:.3g}**. This checks the separate high-accuracy planetary solver, not tree accuracy.
2. Tree versus direct gravity on the same 512-particle initial state, measured from a small velocity kick: median relative discrepancy **{100*a['tree_force_relative_median']:.3f}%**, 95th percentile **{100*a['tree_force_relative_p95']:.3f}%**, maximum **{100*a['tree_force_relative_max']:.3f}%** at theta=0.5.
3. Evolve a 512-particle softened cloud for 0.5 model time units. Energy is calculated independently using the same softened pair potential. Halving the direct-solver timestep reduces energy error approximately fourfold, consistent with second-order leapfrog integration.
4. Tightening tree theta from 0.5 to 0.3 reduces energy drift and position discrepancy; the scaling table uses theta=0.5, not the more accurate setting.

| Solver | Theta | Timestep | Relative energy change | Position RMS vs direct half timestep |
|---|---:|---:|---:|---:|
'''
for r in checks:text+=f"| {r['solver']} | {r['theta']} | {r['dt']} | {r['relative_energy_error']:.6g} | {r['position_rms_vs_direct_half_dt']:.6g} |\n"
text+='''
## What to build with this

- **Interactive exploration:** start with 3,000–10,000 gravitating particles and decouple rendered frames from physics steps. Actual UI frame rate has not been benchmarked.
- **Offline galaxy experiments:** 30,000–100,000 particles are a practical initial design range based on these timings. Save snapshots for smooth playback.
- **Higher resolution:** 300,000 particles was tested successfully; budget hours for long runs. One million remains unmeasured unless a supplemental result is included below.
- **Dense star clusters:** these timings use softened gravity. Close binary encounters and collisional cluster evolution need an appropriate solver and a separate benchmark; these results do not validate them.
- **Galaxies:** particles represent samples of stellar/dark-matter mass. A stable disk, halo, physical unit system and timestep-convergence tests are still required. The test cloud is not a realistic or equilibrium galaxy.

No physical duration in years is claimed: the benchmark uses G=1, total mass=1, radius=1, softening=0.02, timestep=0.00001 and a uniform spherical distribution with Gaussian velocities. A physical length and mass scale would define the time unit; a scientifically acceptable timestep must then be validated for the intended system.

## Reproduce

From the task directory:

```sh
work/venv/bin/python outputs/gravity_benchmark.py
work/venv/bin/python outputs/make_report.py
```

The first command overwrites benchmark_results.json and runs the complete suite, including the ten-minute sustained test. To use a fresh environment, create a Python virtual environment and install the versions in requirements.txt. The resource sampler used here is supplied separately as resource_monitor.py; it should run while the benchmark is active.

## References

- [REBOUND gravity solvers](https://rebound.hanno-rein.de/gravity/): direct summation and Barnes–Hut tree methods.
- [REBOUND documentation](https://rebound.hanno-rein.de/): integrators and scientific scope.

Raw measurements are in benchmark_results.json and resource_samples.jsonl. Source is in gravity_benchmark.py. Charts display measured values only.
'''
(P/'BENCHMARK_REPORT.md').write_text(text)
print(json.dumps(dict(sustained_rate=rate,first_two_minutes=first,last_two_minutes=last,change_percent=(last/first-1)*100),indent=2))
