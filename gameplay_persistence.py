"""JSON codecs for logical city state and active shared transport.

World geometry/inventories live in persistence.py. This module binds saved IDs
back to that world, never creates a second inventory ledger.
"""
from collections import Counter, deque
from copy import deepcopy
from dataclasses import asdict, fields
from math import isfinite
import heapq

from car_brain import CarBrain, BehaviorState, SignalIntent
from households import Household, HousingMemory
from intersection_controls import StopArrival
from mobility import MobilityLink, LaneTraversal, PortTraversal, nearest_lane_position
from pathfinding import Path
from pedestrian_mobility import WalkingRoute
from persistent_fleet import FleetVehicle
from town_simulation import Resident
from traffic_testbed import RoutedRoadVehicle
from transit import TransitSimulation, BusStop, BusLine, Bus, Passenger
from vehicle import VehicleAppearance


def _tuples(value):
    return tuple(_tuples(x) for x in value) if isinstance(value,list) else value


def _walk_dump(route):
    if route is None:return None
    return dict(points=route.points,length=route.length,crossing=route.first_crossing_fraction)


def _walk_load(data):
    if data is None:return None
    return WalkingRoute(tuple(tuple(p) for p in data['points']),(),data['length'],data['crossing'])


def _links(city):
    lanes={lane.id:lane for road in city.roads for lane in road.lanes}
    connections={c.id:c for j in city.intersections for c in j.lane_connections}
    ports={p.id:p for j in city.intersections for p in (*j.incoming_ports(),*j.outgoing_ports())}
    return lanes,connections,ports


def _route_dump(route):
    edges=[]
    for edge in route.edges:
        v=edge.value
        if edge.kind=='lane':
            data=dict(kind='lane',lane=getattr(v,'lane',v).id)
            if hasattr(v,'lane'):data['points']=v.points
        elif edge.kind=='road_port':
            data=dict(kind='road_port',lane=v.lane.id,port=v.port.id,points=v.points)
        elif edge.kind=='lane_connection':data=dict(kind='lane_connection',connection=v.id)
        else:raise ValueError('Unsupported saved vehicle link: '+edge.kind)
        edges.append(data)
    return dict(nodes=route.nodes,edges=edges,cost=route.cost)


def _route_load(data,index):
    lanes,connections,ports=index;edges=[]
    for edge in data['edges']:
        kind=edge['kind']
        if kind=='lane':
            lane=lanes[edge['lane']]
            value=LaneTraversal(lane,tuple(map(tuple,edge['points']))) if 'points' in edge else lane
        elif kind=='road_port':value=PortTraversal(ports[edge['port']],lanes[edge['lane']],tuple(map(tuple,edge['points'])))
        elif kind=='lane_connection':value=connections[edge['connection']]
        else:raise ValueError('Unsupported saved vehicle link')
        edges.append(MobilityLink(kind,value))
    return Path(_tuples(data['nodes']),tuple(edges),data['cost'])


def dump_transport(transit, managed=None):
    traffic=transit.traffic
    controller=traffic._native_backend(transit.city)
    publishing=controller.publishing
    controller.publishing=True
    try:controller.publish_bookkeeping()
    finally:controller.publishing=publishing
    actors=[]
    for a in traffic.cars:
        if managed is not None and a.id not in managed and a.source_type!='test_traffic':continue
        actors.append(dict(id=a.id,source_id=a.source_id,destination_id=a.destination_id,
            route=_route_dump(a.route),points=a.points,speed=a.speed,color=a.color,
            appearance=asdict(a.appearance),source_type=a.source_type,speed_cap_mph=a.speed_cap_mph,
            length=a.length,width=a.width,distance=a.distance,brain=asdict(a.brain),
            merge_entry_speed=a._merge_entry_speed,position=a.position))
    routes={i:key for key,i in transit._walk_routes.items()}
    walkers=[]
    for p in transit.engine.pedestrian_states():
        points,crossing=routes[p.lane]
        walkers.append(dict(id=p.id,points=points,crossing=crossing,distance=p.distance,
                            waiting=bool(p.waiting),position=(p.x,p.y)))
    buses=[]
    for bus in transit.buses.values():
        data={f.name:getattr(bus,f.name) for f in fields(bus) if not f.name.startswith('_')}
        if not isfinite(data['service_until']):data['service_until']=None
        buses.append(data)
    people=[]
    for p in transit.people.values():
        data={f.name:getattr(p,f.name) for f in fields(p) if f.name!='final_walk'}
        data['final_walk']=_walk_dump(p.final_walk);people.append(data)
    return dict(time=transit.time,actors=actors,walkers=walkers,people=people,buses=buses,
        stops=[dict(id=s.id,lane=s.road_position.lane.id,distance=s.road_position.distance,walk_point=s.walk_point)
               for s in transit.stops.values()],lines=[asdict(l) for l in transit.lines.values()],
        line_plans=[asdict(l) for l in transit.line_plans.values()],
        queues=[dict(line=k[0],stop=k[1],people=list(v)) for k,v in transit.queues.items()],
        next_departure=transit._next_departure,
        claims=[(pid,c.id) for (pid,_),c in traffic.stop_coordinator.claims.items()],
        arrivals=[(a.car_id,a.connection.id,a.stopped_at) for a in traffic.stop_coordinator.arrivals.values()],
        rng=traffic.rng.getstate(),sources=list(traffic.active_junction_ids),source_times=dict(traffic._spawn_elapsed),
        spawned=traffic._spawned_count,spawn_interval=traffic.spawn_interval,max_cars=traffic.max_cars,
        vehicle_arrivals=[a.id for a in transit.vehicle_arrivals],person_arrivals=list(transit.person_arrivals))


def restore_transport(transit,data):
    from mobility import lane_position_at_distance
    traffic=transit.traffic;traffic.clear_vehicles()
    index=_links(transit.city);lanes,connections,ports=index
    transit.time=traffic.elapsed_time=float(data['time'])
    transit.stops.clear();transit.lines.clear();transit.buses.clear();transit.people.clear()
    transit.legs.clear();transit.leg_lengths.clear();transit.queues.clear();transit._next_departure.clear();transit.line_plans.clear()
    transit._walk_routes.clear();transit._walk_cache.clear()
    for stop in data['stops']:
        transit.add_stop(BusStop(stop['id'],lane_position_at_distance(lanes[stop['lane']],stop['distance']),tuple(stop['walk_point'])))
    for line in data.get('line_plans',data['lines']):
        line=BusLine(**dict(line,stop_ids=tuple(line['stop_ids'])))
        transit.line_plans[line.id]=line
        try:transit.add_line(line)
        except ValueError:pass
    for info in data['buses']:
        initial={f.name:info[f.name] for f in fields(Bus) if f.init and f.name in info}
        if initial['service_until'] is None:initial['service_until']=float('inf')
        bus=Bus(**initial)
        if bus.line_id not in transit.line_plans:raise ValueError('Bus refers to an unknown saved line')
        if bus.line_id in transit.lines:transit.add_bus(bus)
        else:transit.buses[bus.id]=bus
        for k,v in info.items():
            if k!='service_until':setattr(bus,k,v)
    for info in data['people']:
        info=dict(info);info['origin']=tuple(info['origin']);info['destination']=tuple(info['destination'])
        info['final_walk']=_walk_load(info['final_walk'])
        p=Passenger(**info);transit.people[p.id]=p
    for q in data['queues']:transit.queues[(q['line'],q['stop'])]=deque(q['people'])
    transit._next_departure.update(data['next_departure'])
    actors={}
    for info in data['actors']:
        info=dict(info);route=_route_load(info.pop('route'),index)
        position=info.pop('position');brain=info.pop('brain');distance=info.pop('distance');entry=info.pop('merge_entry_speed')
        info['appearance']=VehicleAppearance(**info['appearance']);speed=info['speed'];info['speed']=max(.001,speed)
        info['points']=tuple(map(tuple,info['points']))
        actor=RoutedRoadVehicle(route=route,**info);actor.place(distance);actor.speed=speed
        brain['state']=BehaviorState(brain['state']);brain['signal_intent']=SignalIntent(brain['signal_intent'])
        actor.brain=CarBrain(**brain);actor._merge_entry_speed=entry
        actors[actor.id]=actor
    with traffic._roster_revision.mutate():traffic._cars.extend(actors.values())
    traffic._occupancy_dirty=True
    for pid,cid in data.get('claims',[]):
        if pid in actors:traffic.stop_coordinator._store_claim(pid,connections[cid])
    for pid,cid,when in data.get('arrivals',[]):
        if pid in actors:traffic.stop_coordinator.arrivals[pid]=StopArrival(pid,connections[cid],when)
    traffic.rng.setstate(_tuples(data['rng']))
    traffic._active_junction_ids[:]=data.get('sources',[])
    traffic._spawn_elapsed.update(data.get('source_times',{}))
    traffic._spawned_count=data.get('spawned',0)
    traffic.spawn_interval=data.get('spawn_interval',10000);traffic.max_cars=data.get('max_cars',12)
    transit.engine=traffic._native_backend(transit.city).engine
    transit.revision=transit.city.mobility_revision
    for info in data['walkers']:
        key=(tuple(map(tuple,info['points'])),info['crossing'])
        if key not in transit._walk_routes:transit._walk_routes[key]=transit.engine.register_pedestrian_lane(*key)
        transit.engine.spawn_pedestrian(info['id'],transit._walk_routes[key],4.4)
        transit.engine.place_pedestrian(info['id'],info['distance'],info['waiting'])
    for bus in transit.buses.values():
        bus._car=actors.get(bus.id)
        if bus._car is not None:bus._last_distance=bus._car.distance
    transit.vehicle_arrivals=deque(actors[pid] for pid in data.get('vehicle_arrivals',[]) if pid in actors)
    transit.person_arrivals=deque(data.get('person_arrivals',[]))
    return actors


METRICS=('produced','consumed','unmet','deliveries','workers_arrived','initial_resources','initial_fuel',
         'imported_resources','harvested','medical_sinks','treated','meals_served')


def dump_city(city):
    # Flush completed movement events into logical records before taking state.
    city._arrivals()
    managed=set(city.fleet.vehicles)|set(city.transit.buses)
    return dict(schema='city.gameplay.v1',time=city.time,
        residents=[asdict(p) for p in city.residents.values()],households=[asdict(h) for h in city.households.values()],
        fleet=[{f.name:getattr(v,f.name) for f in fields(v) if not f.name.startswith('_')} for v in city.fleet.vehicles.values()],
        transport=dump_transport(city.transit,managed),events=deepcopy(city._events),scheduled=sorted(city._scheduled),
        sequence=city._sequence,next_person=city._next_person,next_household=city._next_household,
        jobs=deepcopy(city.jobs),handling={k:list(v) for k,v in city.handling.items()},bay_active=deepcopy(city.bay_active),
        visits=deepcopy(city.visits),care_queue=list(city.care_queue),care_tasks=deepcopy(city.care_tasks),
        meal_queues={k:list(v) for k,v in city.meal_queues.items()},meal_credit=dict(city.meal_credit),meal_capacity=dict(city.meal_capacity),
        metrics={k:getattr(city,k) for k in METRICS},counters=dict(city.counters),resource_journal=dict(city.resource_journal),
        suspended_walkers=city._suspended_walkers,resuming_vehicles=city._resuming_vehicles,resuming_buses=city._resuming_buses,
        last_economy=city._last_economy,last_construction=city._last_construction,candidate_cursor=city._candidate_cursor)


def restore_city(city,raw):
    data=deepcopy(raw)
    try:
        if data['schema']!='city.gameplay.v1' or not isfinite(data['time']) or data['time']<0:
            raise ValueError('Unsupported gameplay snapshot')
        residents={p['id']:Resident(**p) for p in data['residents']}
        households={}
        members=[];occupancy=Counter()
        for info in data['households']:
            info=dict(info);info['memory']=HousingMemory(**info['memory']);h=Household(**info)
            if h.id in households or h.home not in city.sites or not h.members or len(h.members)>4:
                raise ValueError('Invalid saved household')
            if not set(h.arrived)<=set(h.members):raise ValueError('Unknown relocation arrivals')
            for pid in h.members:
                if pid not in residents or residents[pid].home!=h.home:raise ValueError('Unknown household member or address')
            occupancy[h.home]+=len(h.members)
            if h.moving_to:
                if h.moving_to not in city.sites:raise ValueError('Unknown relocation target')
                occupancy[h.moving_to]+=len(h.members)
            households[h.id]=h;members.extend(h.members)
        if len(members)!=len(set(members)) or set(members)!=set(residents):raise ValueError('Household membership must cover each resident once')
        for sid,count in occupancy.items():
            if count>city.sites[sid]['building'].residents:raise ValueError('Housing capacity exceeded')
        if len(residents)!=len(data['residents']):raise ValueError('Duplicate resident ID')
        city.residents,city.households=residents,households
        city._membership={pid:h.id for h in households.values() for pid in h.members}
        city.time=data['time']
        actors=restore_transport(city.transit,data['transport'])
        city.fleet.vehicles.clear();city.fleet.routes.clear()
        for info in data['fleet']:
            v=FleetVehicle(**info)
            if v.id in city.fleet.vehicles or v.site not in city.sites:raise ValueError('Invalid saved fleet')
            v._actor=actors.get(v.id)
            if v.phase=='driving' and v._actor is None:raise ValueError('Missing active fleet actor')
            if v._actor is not None:v._last=v._actor.distance
            city.fleet.vehicles[v.id]=v
        city._events=[tuple(e) for e in data['events']];heapq.heapify(city._events)
        city._scheduled=set(data['scheduled']);city._sequence=data['sequence']
        city._next_person=data['next_person'];city._next_household=data['next_household']
        city.jobs=data['jobs'];city.handling={sid:deque(v) for sid,v in data['handling'].items()}
        city.bay_active={sid:tuple(v) for sid,v in data['bay_active'].items()}
        city.visits={int(pid):v for pid,v in data['visits'].items()}
        city.care_queue=deque(data['care_queue']);city.care_tasks=data['care_tasks']
        city.meal_queues={sid:deque(v) for sid,v in data['meal_queues'].items()};city.meal_credit=Counter(data['meal_credit']);city.meal_capacity=Counter(data.get('meal_capacity',{}))
        for key,value in data['metrics'].items():setattr(city,key,value)
        city.resource_journal=Counter(data.get('resource_journal',{}))
        city.counters=Counter(data['counters']);city._last_economy=data['last_economy']
        city._last_construction=data['last_construction'];city._candidate_cursor=data['candidate_cursor']
        city._suspended_walkers={int(k):v for k,v in data.get('suspended_walkers',{}).items()}
        city._resuming_vehicles=data.get('resuming_vehicles',{})
        city._resuming_buses=data.get('resuming_buses',{})
        city._refresh_occupancy();city._bind_arrivals()
    except (KeyError,TypeError,IndexError) as error:
        raise ValueError('Invalid city gameplay snapshot: '+str(error)) from error


def rebind_transport(city):
    """Keep logical records on an edited graph and replan active journeys."""
    old=city.transit;traffic=old.traffic
    # Read old native progress before sync_network retires its geometry.
    try:
        if not old.engine._ptr:raise RuntimeError('Native transport cleared')
        data=dump_transport(old,set(city.fleet.vehicles)|set(old.buses))
    except (ValueError,RuntimeError):
        data=getattr(city,'_transport_backup',None)
        if data is None:raise RuntimeError('Transport was cleared before its logical state was captured')
    positions={a['id']:a['position'] for a in data['actors']}
    walkers={p['id']:p for p in data['walkers']}
    if city.construction is not None:
        city.construction.clear_trips(preserve_deconstruction=True)
    traffic.clear_vehicles();traffic.sync_network(city.city)
    city.transit=TransitSimulation(city.city,traffic)
    city.transit.time=city.time;traffic.elapsed_time=city.time
    city.transit.engine._call('nt_clock',city.time,0.0,0.0)
    city.fleet.transit=city.transit;city.fleet.routes.clear()
    city._building_signature=None;city.sync_buildings()
    # Lines only resume once every stop has usable vehicle access.
    for line in data.get('line_plans',data['lines']):
        line=BusLine(**dict(line,stop_ids=tuple(line['stop_ids'])))
        city.transit.line_plans[line.id]=line
        try:city.transit.add_line(line)
        except ValueError:pass
    pending_buses=dict(city._resuming_buses)
    for info in data['buses']:
        initial={f.name:info[f.name] for f in fields(Bus) if f.init and f.name in info}
        if initial['service_until'] is None:initial['service_until']=float('inf')
        bus=Bus(**initial)
        if bus.line_id in city.transit.lines:city.transit.add_bus(bus)
        else:city.transit.buses[bus.id]=bus
        for k,v in info.items():
            if k!='service_until':setattr(bus,k,v)
        if bus.id not in pending_buses and (info['phase'] in ('driving','resuming','suspended') or bus.line_id not in city.transit.lines):
            line=city.transit.line_plans[bus.line_id]
            target=(bus.stop_index+1)%len(line.stop_ids) if info['phase']=='driving' else bus.stop_index
            pending_buses[bus.id]=(positions.get(bus.id,bus.position),line.stop_ids[target])
        if bus.id in pending_buses:bus.phase='resuming' if bus.line_id in city.transit.lines else 'suspended'
    city._resuming_buses=pending_buses
    # Replan walkers/queues; riding passengers remain attached to the same bus.
    city._suspended_walkers=dict(city._suspended_walkers)
    for info in data['people']:
        final=_walk_load(info['final_walk']);values=dict(info,origin=tuple(info['origin']),destination=tuple(info['destination']),final_walk=final)
        person=Passenger(**values)
        if person.phase=='riding':city.transit.people[person.id]=person;continue
        if person.phase=='arrived':city.transit.people[person.id]=person;continue
        origin=walkers.get(person.id,{}).get('position')
        if origin is None:
            stop=old.stops.get(person.board_stop);origin=stop.walk_point if stop else person.origin
        city._suspended_walkers.setdefault(person.id,(tuple(origin),person.destination))
    city._resuming_vehicles=dict(city._resuming_vehicles)
    for v in city.fleet.vehicles.values():
        if v.phase=='driving':
            v._actor=None;v.phase='parked'
            city._resuming_vehicles[v.id]=(positions.get(v.id,city.sites[v.site]['walk_point']),v.destination)
    city._bind_arrivals();city._once('resume',city.time,'resume')
