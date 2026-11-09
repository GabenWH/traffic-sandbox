"""Translate OSM topology and traffic controls into ordinary city junctions."""
from collections import Counter, defaultdict
from dataclasses import dataclass
import math

from models import ControlDefinition, ControlType, IntersectionKind


@dataclass(frozen=True)
class Roundabout:
    key: tuple[str, str]
    center: tuple[float, float]
    ring_radius: float


def roundabout_components(selected, nodes, project, in_boundary, segment_inside):
    """Collapse complete rings only; shared endpoints join split OSM ways."""
    rings = {ident: refs for ident, record, refs in selected
             if record['tags'].get('junction') == 'roundabout'}
    by_node = defaultdict(set)
    for ident, refs in rings.items():
        for ref in refs:
            by_node[ref].add(ident)
    remaining = set(rings)
    collapsed, removed, incomplete = {}, set(), 0
    while remaining:
        pending = [min(remaining)]
        members, refs = set(), set()
        while pending:
            ident = pending.pop()
            if ident in members:
                continue
            members.add(ident)
            refs.update(rings[ident])
            pending.extend(other for ref in rings[ident] for other in by_node[ref] - members)
        remaining.difference_update(members)
        edges = [edge for ident in members for edge in zip(rings[ident], rings[ident][1:])]
        degree = Counter(ref for edge in edges for ref in edge)
        if (len(refs) < 3 or any(count != 2 for count in degree.values())
                or any(not in_boundary(nodes[ref]) for ref in refs)
                or any(not segment_inside(nodes[a], nodes[b]) for a, b in edges)):
            incomplete += 1
            continue
        points = [project(nodes[ref]) for ref in refs]
        # Bounding-box center avoids bias from uneven OSM vertex density.
        cx = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
        cy = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
        perimeter = sum(math.dist(project(nodes[a]), project(nodes[b])) for a, b in edges)
        radius = max(8.0, perimeter / (2 * math.pi))
        ring = Roundabout(('roundabout', min(members)), (cx, cy), radius)
        collapsed.update((ref, ring) for ref in refs)
        removed.update(members)
    return collapsed, removed, incomplete


def _road_source(road):
    return road.id.split('|', 1)[0].split(':')[1]


def _priority(road, ways):
    highway = ways[_road_source(road)]['tags'].get('highway', '').removesuffix('_link')
    return {'motorway': 0, 'trunk': 0, 'primary': 1, 'secondary': 2,
            'tertiary': 3, 'unclassified': 4, 'residential': 4,
            'living_street': 5}.get(highway, 4)


def _can_travel_to(road, end):
    return road.forward_lane_count > 0 if end == 'end' else road.reverse_lane_count > 0


def apply_controls(city, node_tags, ways, road_refs, junction_keys, project, nodes):
    """Attach stop-line nodes by topology and direction, never spatial proximity."""
    junctions = {}
    ends = {}
    for junction in city.intersections:
        key = junction_keys.get(junction.id, (None,))
        if key[0] == 'node':
            junctions[key[1]] = junction
        for road in junction.connected_roads:
            ends[road.id, junction._road_end_at_junction(road).value] = junction
    policies = defaultdict(dict)
    signal_junctions = set()
    for ref, tags in node_tags.items():
        kind = tags.get('highway')
        if kind not in {'traffic_signals', 'stop', 'give_way'}:
            continue
        control = {'traffic_signals': ControlType.SIGNAL, 'stop': ControlType.STOP,
                   'give_way': ControlType.YIELD}[kind]
        direct = junctions.get(ref)
        crossing = tags.get('crossing') in {'traffic_signals', 'yes', 'marked', 'unmarked'}
        if direct is not None and (len(direct.connected_roads) >= 3 or
                                   kind == 'traffic_signals' and crossing):
            if kind == 'traffic_signals':
                signal_junctions.add(direct.id)
            else:
                for port in direct.incoming_ports():
                    if tags.get('stop') == 'minor' and _priority(port.road, ways) == min(
                            _priority(road, ways) for road in direct.connected_roads):
                        continue
                    policies[direct.id][port.id] = control
            continue
        namespace = 'traffic_signals' if kind == 'traffic_signals' else kind
        direction = tags.get(f'{namespace}:direction', tags.get('direction'))
        candidates = []
        for road in city.roads:
            refs = road_refs.get(road.id, ())
            if ref not in refs:
                continue
            index = refs.index(ref)
            for end in ('start', 'end'):
                if not _can_travel_to(road, end):
                    continue
                travel = 'backward' if end == 'start' else 'forward'
                if direction in {'forward', 'backward'} and direction != travel:
                    continue
                if direction not in {None, '', 'both', 'forward', 'backward'}:
                    # OSM supports compass bearings; do not guess their meaning.
                    continue
                span = refs[:index+1] if end == 'start' else refs[index:]
                distance = sum(math.dist(project(nodes[a]), project(nodes[b]))
                               for a, b in zip(span, span[1:]))
                target_road, target_end = road, end
                visited = set()
                junction = ends.get((target_road.id, target_end))
                # A change of OSM way/name is not a traffic intersection.
                while (junction is not None and junction.kind is IntersectionKind.STANDARD
                       and len(junction.connected_roads) == 2):
                    key = junction_keys.get(junction.id, (None,))
                    junction_tags = node_tags.get(key[1], {}) if key[0] == 'node' else {}
                    if (junction_tags.get('highway') == 'traffic_signals'
                            and junction_tags.get('crossing') not in {None, '', 'no'}):
                        break
                    if junction.id in visited:
                        junction = None
                        break
                    visited.add(junction.id)
                    other = next(r for r in junction.connected_roads if r is not target_road)
                    near = junction._road_end_at_junction(other).value
                    next_end = 'end' if near == 'start' else 'start'
                    if (not _can_travel_to(other, next_end) or not any(
                            c.source_output.road is target_road and c.destination_input.road is other
                            for c in junction.lane_connections)):
                        junction = None
                        break
                    target_road, target_end = other, next_end
                    distance += sum(math.dist(a, b) for a, b in zip(other.centerline, other.centerline[1:]))
                    junction = ends.get((target_road.id, target_end))
                if (junction is None or len(junction.connected_roads) < 3
                        or junction.kind is not IntersectionKind.STANDARD):
                    continue
                for port in junction.incoming_ports():
                    if port.road is target_road:
                        candidates.append((distance, junction.id, port.id, control, travel))
        # An undirected sign belongs to its nearest downstream junction, not both.
        if candidates:
            chosen = [min(candidates)]
            if direction == 'both':
                chosen = [min(group) for travel in ('forward', 'backward')
                          if (group := [c for c in candidates if c[-1] == travel])]
            for _, ident, port, value, _ in chosen:
                if kind == 'traffic_signals':
                    signal_junctions.add(ident)
                else:
                    policies[ident][port] = value

    inferred = 0
    for junction in city.intersections:
        if junction.kind is not IntersectionKind.STANDARD:
            continue
        if junction.id in signal_junctions:
            junction.signalized = True
            for connection in junction.lane_connections:
                connection.control = ControlDefinition(ControlType.SIGNAL, junction.id)
        elif junction.id in policies:
            for connection in junction.lane_connections:
                connection.control = ControlDefinition(
                    policies[junction.id].get(connection.source_output.id, ControlType.UNCONTROLLED))
        elif len(junction.connected_roads) >= 3:
            tags = [ways[_road_source(road)]['tags'] for road in junction.connected_roads]
            if any(t.get('junction') == 'roundabout' or
                   t.get('highway', '').startswith(('motorway', 'trunk')) for t in tags):
                continue
            priority = {road.id: _priority(road, ways) for road in junction.connected_roads}
            best = min(priority.values())
            for connection in junction.lane_connections:
                stop = best >= 4 or len(set(priority.values())) == 1 or (
                    priority[connection.source_output.road.id] > best)
                connection.control = ControlDefinition(ControlType.STOP if stop else ControlType.UNCONTROLLED)
            inferred += 1
    return {'mapped_signal_intersections': len(signal_junctions),
            'mapped_sign_intersections': len(policies),
            'inferred_stop_intersections': inferred}
