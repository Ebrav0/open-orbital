"""Check physical sanity, duration coverage, and completeness of saved measurements."""
import json,math
from pathlib import Path
P=Path(__file__).parent
d=json.loads((P/'benchmark_results.json').read_text());a=d['accuracy']
assert a['two_body_100_orbits_relative_energy_error']<1e-10
c=a['cloud_checks'];ratio=c[0]['relative_energy_error']/c[1]['relative_energy_error']
assert 3.5<ratio<4.5,ratio
assert c[3]['relative_energy_error']<c[2]['relative_energy_error']/10
assert c[3]['position_rms_vs_direct_half_dt']<c[2]['position_rms_vs_direct_half_dt']
assert {(r['solver'],r['n']) for r in d['scaling']}=={('basic',n) for n in [1000,3000,10000]}|{('tree',n) for n in [1000,3000,10000,30000,100000,300000]}
for r in d['scaling']:
    assert len(r['repeat_s'])==3 and all(math.isfinite(t) and t>0 for t in r['repeat_s'])
for r in d['parallel']+[d['sustained']]:
    assert len(r['results'])==r['workers']
    for w in r['results']:
        assert w['wall_s']>=r['duration_s']-.5
        assert sum(b['steps'] for b in w['buckets'])==w['steps']
for threads in [1,4,8,10,14]:
    p=P/f'openmp_{threads}.json'
    if p.exists():
        o=json.loads(p.read_text());assert all(r['seconds_per_step']>0 for r in o['rows'])
        if threads==8:
            assert o['accuracy']['two_body_100_orbits_relative_energy_error']<1e-10
            assert abs(o['accuracy']['tree_force_relative_median']-a['tree_force_relative_median'])<1e-6
print('PASS: orbit accuracy, timestep convergence, tighter-tree improvement, scaling coverage, and sustained duration/step accounting.')
