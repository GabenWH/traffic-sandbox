"""Compare a supplied pre-consolidation checkout with the current C++ driver."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

# Child processes isolate imported code and compiler caches. Canonical phase
# grouping uses geometry so generated connection IDs cannot change the load.
CHILD = r'''
import json, sys
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from tools.benchmark_native_spawning import make_city
from tools.benchmark_native_shared import run
from intersection_controls import FixedTimeSignalController, SignalPhase, SignalPlan, movements_conflict
fleet=int(sys.argv[2])
city,_=make_city('signalized-crossing',42,max(1200,2*((fleet+3)//4*36+150)))
connections={}
for node in city.mobility.layers['vehicles'].graph.nodes:
    for t in city.mobility.layers['vehicles'].graph.transitions_from(node):
        if t.edge.kind=='lane_connection': connections[t.edge.value.id]=t.edge.value
groups=[]
for c in sorted(connections.values(),key=lambda c:(c.source_output.position,c.source_output.heading,c.destination_input.position,c.maneuver.angle)):
    for g in groups:
        if all(o.source_output==c.source_output or not movements_conflict(c,o) for o in g):
            g.append(c)
            break
    else: groups.append([c])
controller=FixedTimeSignalController(SignalPlan(tuple(SignalPhase(8,{c.id for c in g},1.5,.5) for g in groups)))
a=SimpleNamespace(seed=42,warmup=5,seconds=30,dt=.05)
r=run(city,{'profile-signal':controller},'copy',fleet,True,a)
r.pop('samples')
print(json.dumps(r))
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    current=Path(__file__).resolve().parents[1]
    runs=[]
    comparisons=[]
    for fleet in (60,1000):
        selected=[]
        for repeat in range(3):
            order=('before','cpp') if repeat%2==0 else ('cpp','before')
            pair=[]
            for label in order:
                root=a.baseline_root if label=='before' else current
                result=subprocess.run([sys.executable,'-c',CHILD,str(root),str(fleet)],capture_output=True,text=True)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                r=json.loads(result.stdout)
                r.update(version=label,repeat=repeat+1)
                pair.append(r)
                runs.append(r)
                selected.append(r)
            assert pair[0]['completed']==pair[1]['completed']
            assert pair[0]['mean_active']==pair[1]['mean_active']
            assert abs(pair[0]['display_checksum']-pair[1]['display_checksum'])<1e-6
        cpu={label:statistics.fmean(r['cpu_ms']['mean'] for r in selected if r['version']==label) for label in ('before','cpp')}
        summary={'initial_cars':fleet,'cpu_ms_per_update':cpu,'cpu_reduction':1-cpu['cpp']/cpu['before'],'matching_counts_and_display_checksum':True}
        comparisons.append(summary)
        print(json.dumps(summary),flush=True)
    report={'method':'3 counterbalanced pairs, 30 measured simulated seconds + 5 warmup, dt .05; native copy output with display reads, canonical geometry-based signal groups, compilation/setup excluded',
            'baseline_root':str(a.baseline_root),'current_root':str(current),'comparisons':comparisons,'runs':runs}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__': main()
