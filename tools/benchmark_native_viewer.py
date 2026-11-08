#!/usr/bin/env python3
"""Matched scene-update measurements; rendering is timed separately on Mesa/GPU.

Fixed active snapshots do not advance traffic. Metadata publication is excluded
from steady-state update means and reported separately. Optional Arcata import
uses the bundled real map, buildings and inferred parking.
"""
from pathlib import Path
import argparse,json,statistics,sys,time,platform,hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def summarize(samples):
    ordered=sorted(samples)
    return dict(mean_ms=statistics.fmean(samples),median_ms=statistics.median(samples),
                p95_ms=ordered[int(.95*(len(samples)-1))],samples_ms=samples)


def measure(fn,n=100,warmup=5):
    for _ in range(warmup):fn()
    samples=[]
    for _ in range(n):
        t=time.perf_counter();fn();samples.append((time.perf_counter()-t)*1000)
    return summarize(samples)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--arcata',action='store_true')
    p.add_argument('--counts',type=int,nargs='+',default=[1,60,250,1000])
    p.add_argument('--samples',type=int,default=100)
    args=p.parse_args()
    if args.samples<2 or any(n<1 for n in args.counts):p.error('positive counts and at least two samples required')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    from panda3d.core import NodePath
    from native_viewer import NativeScene
    from ui.scene_presenter import ScenePresenter
    from tools.benchmark_native_shared import setup
    from tools.benchmark_native_spawning import make_city
    from ui.scene3d import update_road_vehicle_layer
    from panda3d.core import PandaSystem
    sources=[ROOT/'native_viewer.py',ROOT/'ui/scene_presenter.py',ROOT/'ui/scene_buffers.py',
             ROOT/'ui/scene3d.py',Path(__file__),*sorted((ROOT/'native/viewer').glob('*.cpp')),
             ROOT/'native/viewer/scene.h']
    report=dict(python=sys.version,platform=platform.platform(),fixed_fleets=[],
        panda_version=PandaSystem.get_version_string(),source_sha256=hashlib.sha256(b''.join(p.read_bytes() for p in sources)).hexdigest(),
        method='Matched real actors with fixed poses; no traffic stepping. Each case runs both orders with a warmup for each order. Steady-state CPU presentation excludes graphics and metadata. Native camera omitted so every actor is visible. Graphics timings are separate software/hardware-dependent measurements.')
    for count in args.counts:
        city,controls=make_city('signalized-crossing',42,max(1200,2*((count+3)//4*36+150)))
        sim=setup(city,controls,'copy',count,42)
        root=NodePath('native-benchmark');scene=NativeScene(root);presenter=ScenePresenter(scene)
        old_root=NodePath('old-benchmark');nodes={}
        try:
            start=time.perf_counter();presenter.update(city,sim);metadata_ms=(time.perf_counter()-start)*1000
            for car in sim.vehicles:car.elevation=0.
            def legacy():update_road_vehicle_layer(sim.vehicles,city,old_root,nodes,sim.elapsed_time)
            functions=[('legacy_height_supplied',legacy),('native',lambda:presenter.update(city,sim))]
            samples={name:[] for name,_ in functions}
            for order in (functions,list(reversed(functions))):
                for name,fn in order:samples[name].extend(measure(fn,args.samples)['samples_ms'])
            timings={name:summarize(values) for name,values in samples.items()}
            poses=scene.snapshot()
            assert len(poses)==count
            expected={sim._native_controller.engine._handles[c.id]:c for c in sim.vehicles}
            for pose in poses:
                car=expected[pose['handle']]
                assert abs(pose['x']-car.position[0])<1e-7 and abs(pose['y']-car.position[1])<1e-7
                assert abs(pose['z'])<1e-7
            row=dict(cars=count,initial_metadata_ms=metadata_ms,timings=timings,scene=scene.stats())
            report['fixed_fleets'].append(row)
            print(json.dumps(dict(cars=count,native_ms=timings['native']['mean_ms'],
                legacy_height_supplied_ms=timings['legacy_height_supplied']['mean_ms'],scene=scene.stats())),flush=True)
        finally:scene.close();sim._discard_native()
    if args.arcata:
        from ui.view3d import PandaWorldView
        from tools.run_arcata_scale_test import build_city
        t=time.perf_counter()
        city,_,_=build_city([ROOT/'benchmarks/arcata/arcata-roads-2026-06-01.json'],
            ROOT/'benchmarks/arcata/arcata-city-boundary.osm',
            building_paths=[ROOT/'benchmarks/arcata/arcata-buildings-citywide-2026-11-04.json.gz'])
        setup_seconds=time.perf_counter()-t
        view=PandaWorldView(offscreen=True,mode='map')
        try:
            t=time.perf_counter();view.show_city(city);upload_ms=(time.perf_counter()-t)*1000
            g=view.base.win.getGsg()
            data=dict(roads=len(city.roads),buildings=len(city.buildings),parking_lots=len(city.parking_lots),
                setup_seconds=setup_seconds,compile_and_upload_ms=upload_ms,scene=view.native_scene.stats(),
                driver=g.getDriverRenderer(),viewport=[960,640],render={})
            for mode in ('map','perspective'):
                view.orbit.target=(0,0,0);view.orbit.distance=10000
                if mode=='map':view.map_view.x=-4800;view.map_view.y=-3200;view.map_view.zoom=.1
                view.set_mode(mode)
                def render():view.base.graphicsEngine.renderFrame();view.base.graphicsEngine.syncFrame()
                data['render'][mode]=measure(render,30)
                view.base.win.getScreenshot().write(str(args.output.with_name('arcata-native-'+mode+'.png')))
            report['arcata']=data
            print(json.dumps(dict(arcata_scene=data['scene'],driver=data['driver'],
                render={k:v['mean_ms'] for k,v in data['render'].items()})),flush=True)
        finally:view.close()
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print('Wrote',args.output,flush=True)

if __name__=='__main__':main()
