#!/usr/bin/env python3
"""Run a headless traffic scale test on Arcata's OSM street geometry.

This is a one-off benchmark harness. It does not change the simulation product
or add GPS traces to the repository. The OSM boundary and street extracts are
kept alongside the run results for provenance.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import random
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from city import CityMap, Terrain
from models import Intersection, Road
from simulation_profiler import SimulationProfiler
from traffic_testbed import RoadVehicleSimulation


DATA_DIR = ROOT / "benchmarks" / "arcata"
RESULTS_DIR = DATA_DIR / "results"
FRAME_DT = 0.05
FPS_LIMIT = 5.0
WINDOW_FRAMES = 20
DEFAULT_DURATION = 900.0
ROAD_TYPES = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary",
    "primary_link", "secondary", "secondary_link", "tertiary",
    "tertiary_link", "unclassified", "residential", "living_street",
}


@dataclass(frozen=True)
class GeoPoint:
    key: tuple[object, ...]
    lon: float
    lat: float


def parse_boundary(path: Path) -> tuple[list[list[tuple[float, float]]], list[list[tuple[float, float]]], dict[str, object]]:
    tree = ET.parse(path)
    root = tree.getroot()
    nodes = {
        node.attrib["id"]: (float(node.attrib["lon"]), float(node.attrib["lat"]))
        for node in root.findall("node")
    }
    way_nodes = {
        way.attrib["id"]: [nd.attrib["ref"] for nd in way.findall("nd")]
        for way in root.findall("way")
    }
    relation = None
    for candidate in root.findall("relation"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in candidate.findall("tag")}
        if tags.get("name") == "Arcata" and tags.get("boundary") == "administrative":
            relation = candidate
            break
    if relation is None:
        raise RuntimeError("Arcata administrative boundary relation is missing from its OSM XML")
    tags = {tag.attrib["k"]: tag.attrib["v"] for tag in relation.findall("tag")}
    members: dict[str, list[list[str]]] = {"outer": [], "inner": []}
    for member in relation.findall("member"):
        if member.attrib.get("type") == "way" and member.attrib.get("role") in members:
            refs = way_nodes.get(member.attrib["ref"])
            if refs:
                members[member.attrib["role"]].append(refs)

    def stitch(chains: list[list[str]]) -> list[list[str]]:
        pending = [list(chain) for chain in chains]
        rings: list[list[str]] = []
        while pending:
            chain = pending.pop(0)
            while chain[-1] != chain[0]:
                match = None
                for index, part in enumerate(pending):
                    if chain[-1] == part[0]:
                        match = (index, part)
                        break
                    if chain[-1] == part[-1]:
                        match = (index, list(reversed(part)))
                        break
                    if chain[0] == part[-1]:
                        match = (index, part)
                        break
                    if chain[0] == part[0]:
                        match = (index, list(reversed(part)))
                        break
                if match is None:
                    break
                index, part = match
                pending.pop(index)
                if chain[-1] == part[0]:
                    chain.extend(part[1:])
                elif chain[0] == part[-1]:
                    chain = part[:-1] + chain
                elif chain[-1] == part[-1]:
                    part.reverse()
                    chain.extend(part[1:])
                else:
                    part.reverse()
                    chain = part[:-1] + chain
            if chain[0] != chain[-1]:
                raise RuntimeError("Could not stitch a closed ring in Arcata's OSM boundary")
            rings.append(chain)
        return rings

    outer = stitch(members["outer"])
    inner = stitch(members["inner"])
    return (
        [[nodes[node_id] for node_id in ring] for ring in outer],
        [[nodes[node_id] for node_id in ring] for ring in inner],
        {"relation_id": relation.attrib["id"], "tags": tags},
    )


def point_on_segment(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> bool:
    px, py = point
    ax, ay = start
    bx, by = end
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    scale = max(1.0, abs(bx - ax) + abs(by - ay))
    if abs(cross) > 1e-10 * scale:
        return False
    return min(ax, bx) - 1e-10 <= px <= max(ax, bx) + 1e-10 and min(ay, by) - 1e-10 <= py <= max(ay, by) + 1e-10


def point_in_ring(point: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    for a, b in zip(ring, ring[1:]):
        if point_on_segment(point, a, b):
            return True
        if (a[1] > y) != (b[1] > y):
            x_cross = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x < x_cross:
                inside = not inside
    return inside


def point_in_city(point: tuple[float, float], outer: list[list[tuple[float, float]]], inner: list[list[tuple[float, float]]]) -> bool:
    return any(point_in_ring(point, ring) for ring in outer) and not any(point_in_ring(point, ring) for ring in inner)


def segment_intersection_t(
    start: tuple[float, float], end: tuple[float, float],
    edge_start: tuple[float, float], edge_end: tuple[float, float],
) -> float | None:
    rx, ry = end[0] - start[0], end[1] - start[1]
    sx, sy = edge_end[0] - edge_start[0], edge_end[1] - edge_start[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) < 1e-16:
        return None
    qx, qy = edge_start[0] - start[0], edge_start[1] - start[1]
    t = (qx * sy - qy * sx) / denominator
    u = (qx * ry - qy * rx) / denominator
    if -1e-10 <= t <= 1 + 1e-10 and -1e-10 <= u <= 1 + 1e-10:
        return min(1.0, max(0.0, t))
    return None


def clip_segment_to_city(
    start: tuple[float, float], end: tuple[float, float],
    outer: list[list[tuple[float, float]]], inner: list[list[tuple[float, float]]],
) -> list[tuple[float, float]]:
    cuts = {0.0, 1.0}
    for ring in (*outer, *inner):
        for edge_start, edge_end in zip(ring, ring[1:]):
            t = segment_intersection_t(start, end, edge_start, edge_end)
            if t is not None:
                cuts.add(t)
    ordered = sorted(cuts)
    intervals = []
    for a, b in zip(ordered, ordered[1:]):
        if b - a < 1e-10:
            continue
        midpoint = (a + b) / 2
        sample = (start[0] + (end[0] - start[0]) * midpoint, start[1] + (end[1] - start[1]) * midpoint)
        if point_in_city(sample, outer, inner):
            intervals.append((a, b))
    return intervals


def load_osm(paths: list[Path]) -> tuple[dict[str, tuple[float, float]], dict[str, dict[str, object]], dict[str, object]]:
    nodes: dict[str, tuple[float, float]] = {}
    ways: dict[str, dict[str, object]] = {}
    metadata: dict[str, object] = {}
    for path in paths:
        payload = json.loads(path.read_text())
        metadata.update(payload.get("osm3s", {}))
        for element in payload["elements"]:
            if element["type"] == "node":
                nodes[str(element["id"])] = (float(element["lon"]), float(element["lat"]))
            elif element["type"] == "way":
                ways[str(element["id"])] = {
                    "nodes": [str(item) for item in element.get("nodes", [])],
                    "tags": element.get("tags", {}),
                }
                for item, geometry in zip(element.get("nodes", []), element.get("geometry", [])):
                    nodes[str(item)] = (float(geometry["lon"]), float(geometry["lat"]))
    return nodes, ways, metadata


def road_lanes(tags: dict[str, str]) -> tuple[int, int]:
    oneway = tags.get("oneway", "").lower()
    if tags.get("junction") == "roundabout" and not oneway:
        oneway = "yes"
    if oneway in {"yes", "true", "1"}:
        return min(3, max(1, int(tags.get("lanes", "1").split(";")[0]))), 0
    if oneway == "-1":
        return 0, min(3, max(1, int(tags.get("lanes", "1").split(";")[0])))
    total = min(6, max(2, int(tags.get("lanes", "2").split(";")[0])))
    forward = min(3, max(1, int(tags.get("lanes:forward", str(total // 2)))))
    reverse = min(3, max(1, int(tags.get("lanes:backward", str(total - forward)))))
    return forward, reverse


def build_city(paths: list[Path], boundary_path: Path) -> tuple[CityMap, list[str], dict[str, object]]:
    nodes, ways, osm_metadata = load_osm(paths)
    outer, inner, boundary_metadata = parse_boundary(boundary_path)
    boundary_points = [point for ring in outer for point in ring[:-1]]
    lat0 = sum(point[1] for point in boundary_points) / len(boundary_points)
    lon0 = sum(point[0] for point in boundary_points) / len(boundary_points)
    in_boundary = lambda point: point_in_city(point, outer, inner)

    selected: list[tuple[str, dict[str, object], list[str]]] = []
    membership: Counter[str] = Counter()
    for way_id, record in ways.items():
        tags = record["tags"]
        refs = record["nodes"]
        if tags.get("highway") not in ROAD_TYPES or tags.get("access") in {"no", "private"}:
            continue
        if len(refs) < 2 or any(node_id not in nodes for node_id in refs):
            continue
        points = [nodes[node_id] for node_id in refs]
        if not any(in_boundary(point) for point in points) and not any(
            clip_segment_to_city(a, b, outer, inner)
            for a, b in zip(points, points[1:])
        ):
            continue
        selected.append((way_id, record, refs))
        membership.update(set(refs))
    shared_nodes = {node_id for node_id, count in membership.items() if count >= 2}
    shared_keys = {("node", node_id) for node_id in shared_nodes}

    def to_feet(point: tuple[float, float]) -> tuple[float, float]:
        return (
            (point[0] - lon0) * 111_320.0 * math.cos(math.radians(lat0)) * 3.28084,
            (point[1] - lat0) * 111_132.0 * 3.28084,
        )

    roads: list[Road] = []
    endpoint_position: dict[tuple[object, ...], tuple[float, float]] = {}
    portal_keys: set[tuple[object, ...]] = set()
    kept_way_count = 0
    source_segment_count = 0
    clipped_point_count = 0
    for way_id, record, refs in selected:
        tags = record["tags"]
        way_points = [nodes[node_id] for node_id in refs]
        fragments: list[list[GeoPoint]] = []
        current: list[GeoPoint] = []

        def finish_fragment() -> None:
            nonlocal current
            if len(current) >= 2:
                fragments.append(current)
            current = []

        for index, (node_a, node_b, a, b) in enumerate(zip(refs, refs[1:], way_points, way_points[1:])):
            intervals = clip_segment_to_city(a, b, outer, inner)
            if not intervals:
                finish_fragment()
                continue
            last_t = -1.0
            for t0, t1 in intervals:
                if t0 > 1e-9:
                    finish_fragment()
                p0 = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
                p1 = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
                key0: tuple[object, ...] = (("node", node_a) if t0 <= 1e-9 else ("portal", way_id, index, round(t0, 9)))
                key1: tuple[object, ...] = (("node", node_b) if t1 >= 1 - 1e-9 else ("portal", way_id, index, round(t1, 9)))
                gp0, gp1 = GeoPoint(key0, *p0), GeoPoint(key1, *p1)
                if current and current[-1].key == gp0.key:
                    if current[-1] != gp1:
                        current.append(gp1)
                else:
                    finish_fragment()
                    current = [gp0, gp1]
                if key0[0] == "portal":
                    portal_keys.add(key0)
                    clipped_point_count += 1
                if key1[0] == "portal":
                    portal_keys.add(key1)
                    clipped_point_count += 1
                endpoint_position[key0] = p0
                endpoint_position[key1] = p1
                last_t = t1
                if t1 < 1 - 1e-9:
                    finish_fragment()
            if last_t < 1 - 1e-9:
                finish_fragment()
        finish_fragment()

        piece_index = 0
        for fragment in fragments:
            start = 0
            for point_index in range(1, len(fragment)):
                if fragment[point_index].key in shared_keys:
                    piece = fragment[start:point_index + 1]
                    if len(piece) >= 2:
                        add_piece(way_id, tags, piece, piece_index, roads, endpoint_position, portal_keys, to_feet)
                        piece_index += 1
                        source_segment_count += 1
                    start = point_index
            piece = fragment[start:]
            if len(piece) >= 2:
                add_piece(way_id, tags, piece, piece_index, roads, endpoint_position, portal_keys, to_feet)
                piece_index += 1
                source_segment_count += 1
        if piece_index:
            kept_way_count += 1

    unique_endpoints: dict[tuple[object, ...], tuple[float, float]] = {}
    for road in roads:
        # road build metadata is retained in a local map keyed by endpoint id.
        _prefix, start_key, end_key = road.id.split("|", 2)
        # The generated id stores compact JSON-encoded endpoint keys.
        start_tuple = tuple(json.loads(start_key))
        end_tuple = tuple(json.loads(end_key))
        unique_endpoints[start_tuple] = endpoint_position[start_tuple]
        unique_endpoints[end_tuple] = endpoint_position[end_tuple]

    intersections = [
        Intersection(id=f"osm-junction:{json.dumps(list(key), separators=(',', ':'))}", position=to_feet(point))
        for key, point in unique_endpoints.items()
    ]
    projected_endpoints = [to_feet(point) for point in unique_endpoints.values()]
    city = CityMap(
        width=max((p[0] for p in projected_endpoints), default=0) - min((p[0] for p in projected_endpoints), default=0),
        height=max((p[1] for p in projected_endpoints), default=0) - min((p[1] for p in projected_endpoints), default=0),
        terrain=Terrain(trees=[]), roads=roads, intersections=intersections,
    )

    portal_ids = []
    for intersection in city.intersections:
        try:
            key = tuple(json.loads(intersection.id.removeprefix("osm-junction:")))
        except Exception:
            continue
        if key in portal_keys:
            portal_ids.append(intersection.id)
    portal_ids = sorted(set(portal_ids))
    metadata = {
        "boundary_relation_id": boundary_metadata["relation_id"],
        "boundary_name": boundary_metadata["tags"].get("name"),
        "osm_snapshot": osm_metadata.get("timestamp_osm_base", "unknown"),
        "ways_in_extract": len(ways),
        "driveable_ways_in_extract": len(selected),
        "driveable_ways_used": kept_way_count,
        "road_segments": len(roads),
        "street_junctions": len(city.intersections),
        "portal_junctions": len(portal_ids),
        "boundary_clipped_points": clipped_point_count,
        "road_centerline_points": sum(len(road.centerline) for road in roads),
        "network_length_feet": round(sum(sum(math.dist(a, b) for a, b in zip(road.centerline, road.centerline[1:])) for road in roads), 1),
        "roads_by_highway": dict(Counter(road.name.split(" [", 1)[-1].rstrip("]") for road in roads)),
        "osm_file_names": [path.name for path in paths],
    }
    return city, portal_ids, metadata


def posted_speed_mph(tags):
    """Read numeric OSM maxspeed; unknown textual signs use engine fallback."""
    import re
    raw=str(tags.get('maxspeed','')).strip().lower()
    match=re.fullmatch(r'(\d+(?:\.\d+)?)\s*(mph|km/h|kph)?',raw)
    if not match:return None
    value=float(match[1])
    if match[2]!='mph':value/=1.609344
    return value if value>0 else None


def add_piece(
    way_id: str, tags: dict[str, str], points: list[GeoPoint], piece_index: int,
    roads: list[Road], endpoint_position: dict[tuple[object, ...], tuple[float, float]],
    portal_keys: set[tuple[object, ...]], to_feet,
) -> None:
    cleaned: list[GeoPoint] = []
    for point in points:
        if not cleaned or math.dist(to_feet((point.lon, point.lat)), to_feet((cleaned[-1].lon, cleaned[-1].lat))) > 0.5:
            cleaned.append(point)
    if len(cleaned) < 2:
        return
    forward, reverse = road_lanes(tags)
    road_id = "osm-way:{}:{}|{}|{}".format(
        way_id, piece_index,
        json.dumps(list(cleaned[0].key), separators=(",", ":")),
        json.dumps(list(cleaned[-1].key), separators=(",", ":")),
    )
    name = tags.get("name") or tags.get("ref") or tags.get("highway", "street")
    name = f"{name} [{tags.get('highway', 'road')}]"
    road = Road(
        id=road_id, name=name,
        centerline=[to_feet((point.lon, point.lat)) for point in cleaned],
        forward_lane_count=forward, reverse_lane_count=reverse,
        speed_limit_mph=posted_speed_mph(tags),
    )
    roads.append(road)
    for point in (cleaned[0], cleaned[-1]):
        endpoint_position[point.key] = (point.lon, point.lat)
        if point.key[0] == "portal":
            portal_keys.add(point.key)


def choose_portals(city: CityMap, portal_ids: list[str], maximum: int = 16) -> list[Intersection]:
    by_id = {item.id: item for item in city.intersections}
    candidates = [by_id[item] for item in portal_ids if item in by_id]
    if len(candidates) < 2:
        candidates = [item for item in city.intersections if len(item.connected_roads) == 1]
    if len(candidates) < 2:
        candidates = city.intersections
    if len(candidates) < 2:
        return []
    center = (
        statistics.mean(item.position[0] for item in candidates),
        statistics.mean(item.position[1] for item in candidates),
    )
    candidates = sorted(candidates, key=lambda item: math.atan2(item.position[1] - center[1], item.position[0] - center[0]))
    selected = [candidates[0]]
    while len(selected) < min(maximum, len(candidates)):
        next_item = max(
            (item for item in candidates if item not in selected),
            key=lambda item: min(math.dist(item.position, used.position) for used in selected),
        )
        nearest = min(math.dist(next_item.position, used.position) for used in selected)
        if nearest < 300.0:
            break
        selected.append(next_item)
    return selected


def cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def parse_stage_caps(value: str) -> tuple[int, ...]:
    try:
        caps = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("stage caps must be comma-separated positive integers") from error
    if not caps or any(cap < 1 for cap in caps):
        raise argparse.ArgumentTypeError("stage caps must be comma-separated positive integers")
    return caps


def cap_for_staged_run(simulated_time: float, duration: float, caps: tuple[int, ...]) -> int:
    """Choose the evenly staged active-car cap for this simulated time."""
    if not caps or duration <= 0:
        raise ValueError("A staged run needs at least one cap and a positive duration")
    stage_duration = duration / len(caps)
    stage_index = min(len(caps) - 1, max(0, int(simulated_time / stage_duration)))
    return caps[stage_index]


def profile_statistics(samples) -> dict[str, dict[str, float]]:
    block_names = sorted({name for sample in samples for name in sample.timings_ms})
    result = {}
    for name in block_names:
        values = [sample.timings_ms.get(name, 0.0) for sample in samples]
        result[name] = {
            "mean_ms": statistics.mean(values),
            "median_ms": statistics.median(values),
            "p95_ms": percentile(values, 0.95),
            "p99_ms": percentile(values, 0.99),
            "max_ms": max(values),
        }
    return result


def run_benchmark(args: argparse.Namespace) -> Path:
    osm_paths = [Path(item).resolve() for item in args.osm]
    boundary_path = Path(args.boundary).resolve()
    city, portal_ids, network = build_city(osm_paths, boundary_path)
    portals = choose_portals(city, portal_ids, args.portal_count)
    if len(portals) < 2:
        raise RuntimeError(f"Need at least two reachable spawn portals; found {len(portals)}")

    duration = args.duration
    if args.stage_caps and duration < len(args.stage_caps) * FRAME_DT:
        raise ValueError("Duration is too short for the requested cap stages")
    initial_cap = args.stage_caps[0] if args.stage_caps else args.initial_cap
    traffic = RoadVehicleSimulation(
        spawn_interval=args.spawn_interval,
        max_cars=initial_cap,
        rng=random.Random(args.seed),
        update_mode="cpp",
    )
    traffic.occupancy.profile_internal_timings = True
    for portal in portals:
        traffic.toggle_junction(portal)

    # Route discovery is a one-time graph search, unlike steady-state vehicle
    # updates. Populate the simulator's normal route cache before timing so an
    # initial Dijkstra search cannot masquerade as the sustained 5 FPS limit.
    traffic.sync_network(city)
    route_precompute_started = time.perf_counter()
    reachable_portal_pairs = 0
    for source in portals:
        for destination in portals:
            if source is destination:
                continue
            route = city.find_vehicle_route_between(source, destination)
            traffic._spawn_routes[(id(source), id(destination))] = route
            reachable_portal_pairs += route is not None
    route_precompute_seconds = time.perf_counter() - route_precompute_started
    if reachable_portal_pairs == 0:
        raise RuntimeError("No directed routes exist between selected Arcata boundary portals")

    # Prime the empty update path, then start clean timing and profiling.
    traffic.update(city, FRAME_DT)
    traffic.elapsed_time = 0.0
    traffic._spawn_elapsed = {item.id: 0.0 for item in portals}
    traffic.profiler = SimulationProfiler(
        max_samples=max(600, int(round(duration / FRAME_DT)) + 1),
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_DIR / (args.label or f"arcata-{timestamp}")
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.json"
    timeseries_path = out_dir / "timeseries.csv"
    profiler_path = out_dir / "profiler.csv"
    steps = int(round(duration / FRAME_DT))
    if abs(steps * FRAME_DT - duration) > 1e-7:
        raise ValueError("Duration must be divisible into 0.05-second simulation frames")

    rows: list[dict[str, float | int | bool]] = []
    bucket: list[tuple[float, int, int, int]] = []
    bucket_start = 0.0
    rolling: deque[float] = deque(maxlen=WINDOW_FRAMES)
    threshold_reached = False
    threshold_at: float | None = None
    threshold_fps: float | None = None
    threshold_active_cars: int | None = None
    cap = initial_cap
    next_ramp_at = args.ramp_interval
    peak_cars = 0
    lowest_rolling_fps = float("inf")
    total_completed = 0
    completed_frames = 0
    wall_started = time.perf_counter()
    last_checkpoint = wall_started
    last_heartbeat = wall_started

    def flush_bucket() -> None:
        nonlocal bucket, bucket_start
        if not bucket:
            return
        elapsed = [row[0] for row in bucket]
        rows.append({
            "simulated_time_seconds": round(bucket_start + len(bucket) * FRAME_DT, 3),
            "target_cap": bucket[-1][1],
            "mean_active_cars": round(statistics.mean(row[2] for row in bucket), 2),
            "max_active_cars": max(row[2] for row in bucket),
            "cumulative_spawned": bucket[-1][3],
            "mean_update_ms": round(statistics.mean(elapsed) * 1000, 3),
            "p95_update_ms": round(percentile(elapsed, .95) * 1000, 3),
            "max_update_ms": round(max(elapsed) * 1000, 3),
            "mean_update_fps": round(1.0 / statistics.mean(elapsed), 2) if statistics.mean(elapsed) > 0 else 0,
            "threshold_reached": threshold_reached,
        })
        bucket_start += len(bucket) * FRAME_DT
        bucket = []

    def save_checkpoint(final: bool = False) -> None:
        flush_bucket()
        wall_elapsed = time.perf_counter() - wall_started
        summary = {
            "status": "complete" if final else "running",
            "started_utc": timestamp,
            "finished_utc": datetime.now(timezone.utc).isoformat() if final else None,
            "duration_simulated_seconds": round(traffic.elapsed_time, 3),
            "requested_duration_simulated_seconds": duration,
            "completed_frames": completed_frames,
            "frame_dt_seconds": FRAME_DT,
            "fps_threshold": FPS_LIMIT,
            "fps_threshold_definition": f"rolling mean CPU update cost across {WINDOW_FRAMES} frames >= 200 ms/frame (5 updates/s)",
            "threshold_reached": threshold_reached,
            "threshold_time_simulated_seconds": threshold_at,
            "threshold_rolling_fps": threshold_fps,
            "threshold_active_cars": threshold_active_cars,
            "lowest_rolling_fps": None if not math.isfinite(lowest_rolling_fps) else round(lowest_rolling_fps, 3),
            "spawn_cap_at_end": cap,
            "peak_active_cars": peak_cars,
            "active_cars_at_end": sum(car.source_type == "test_traffic" for car in traffic.cars),
            "total_spawned": traffic._spawned_count,
            "total_completed": total_completed,
            "portals_used": [item.id for item in portals],
            "portal_count_used": len(portals),
            "reachable_portal_pairs": reachable_portal_pairs,
            "route_precompute_seconds_excluded_from_test": round(route_precompute_seconds, 3),
            "spawn_interval_seconds": args.spawn_interval,
            "ramp_interval_simulated_seconds": args.ramp_interval,
            "ramp_increment_cars": args.ramp_increment,
            "cpu_model": cpu_name(),
            "logical_cpu_count": os.cpu_count(),
            "platform": platform.platform(),
            "python": sys.version,
            "wall_elapsed_seconds": round(wall_elapsed, 3),
            "network": network,
            "profiler_statistics_all_samples": traffic.profiler.statistics(),
            "profiler_statistics_last_600_frames": {
                "routed_traffic": profile_statistics(traffic.profiler.samples[-600:]),
            },
            "cap_stages": list(args.stage_caps),
            "occupancy_internal_profiling": traffic.occupancy.profile_internal_timings,
            "data_note": "OpenStreetMap road geometry, not measured vehicle GPS traces.",
        }
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        if rows:
            with timeseries_path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        if traffic.profiler.samples:
            profiler_path.write_text(traffic.profiler.to_csv())
        if final:
            profile = summary["profiler_statistics_all_samples"].get("routed_traffic", {})
            if threshold_reached:
                if args.stage_caps:
                    limit_result = (
                        f"Reached the 5 updates/s threshold at {threshold_at:.1f} simulated seconds "
                        f"with {threshold_active_cars} active cars ({threshold_fps:.2f} FPS rolling); "
                        "the requested cap stages continued."
                    )
                else:
                    limit_result = (
                        f"Reached the 5 updates/s threshold at {threshold_at:.1f} simulated seconds "
                        f"with {threshold_active_cars} active cars ({threshold_fps:.2f} FPS rolling). "
                        f"The spawn cap was then held at {cap}."
                    )
            else:
                limit_result = (
                    f"Did not reach 5 updates/s in {duration:.0f} simulated seconds. "
                    f"The highest observed cap was {cap}, with {peak_cars} active cars."
                )
            major_phase_names = (
                "total", "spawn", "snapshot", "observe", "intent_generation",
                "conflict_resolution", "movement_apply", "occupancy_rebuild",
            )
            detailed_phase_names = sorted(
                name for name in profile
                if name.startswith("intent_") or name.startswith("occupancy_")
            )

            def phase_rows_for(names, phase_profile):
                phase_rows = []
                for name in names:
                    stats = phase_profile.get(name)
                    if stats:
                        phase_rows.append(
                            f"| `{name}` | {stats['mean_ms']:.3f} | {stats['p95_ms']:.3f} | "
                            f"{stats['p99_ms']:.3f} | {stats['max_ms']:.3f} |"
                        )
                return phase_rows

            phase_rows = phase_rows_for(major_phase_names, profile)
            overall_detailed_rows = phase_rows_for(detailed_phase_names, profile)
            staged_report = []
            if args.stage_caps:
                stage_duration = duration / len(args.stage_caps)
                for index, stage_cap in enumerate(args.stage_caps):
                    stage_start = index * stage_duration
                    stage_end = (index + 1) * stage_duration
                    stage_samples = [
                        sample for sample in traffic.profiler.samples
                        if stage_start <= sample.simulated_time - FRAME_DT + 1e-9 < stage_end
                    ]
                    stage_stats = profile_statistics(stage_samples)
                    stage_key = f"stage_{index + 1}"
                    summary.setdefault("profiler_statistics_by_stage", {})[stage_key] = {
                        "target_cap": stage_cap,
                        "simulated_start_seconds": stage_start,
                        "simulated_end_seconds": stage_end,
                        "sample_count": len(stage_samples),
                        "mean_active_cars": round(statistics.mean(
                            sample.entity_counts.get("cars", 0) for sample in stage_samples
                        ), 2) if stage_samples else 0.0,
                        "statistics": stage_stats,
                    }
                    staged_report.extend([
                        f"### Stage {index + 1}: cap {stage_cap} ({stage_start:.0f}–{stage_end:.0f} simulated seconds)",
                        "",
                        f"Mean active cars: {summary['profiler_statistics_by_stage'][stage_key]['mean_active_cars']}; profiler samples: {len(stage_samples)}.",
                        "",
                        "Overall update phases (milliseconds):",
                        "",
                        "| Phase | Mean | P95 | P99 | Max |",
                        "|---|---:|---:|---:|---:|",
                        *phase_rows_for(major_phase_names, stage_stats),
                        "",
                        "Internal phase timings (milliseconds):",
                        "",
                        "| Internal phase | Mean | P95 | P99 | Max |",
                        "|---|---:|---:|---:|---:|",
                        *phase_rows_for(detailed_phase_names, stage_stats),
                        "",
                    ])
                summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
            cap_description = (
                ", then ".join(f"{cap} cars for {duration / len(args.stage_caps):.0f}s" for cap in args.stage_caps)
                if args.stage_caps else
                f"+{args.ramp_increment} every {args.ramp_interval:g} simulated seconds from {args.initial_cap}"
            )
            report = [
                "# Arcata traffic scale test",
                "",
                f"Run status: **{summary['status']}**. {limit_result}",
                "",
                "## Result",
                "",
                f"- Simulated time: {summary['duration_simulated_seconds']:.1f} / {duration:.0f} seconds ({completed_frames:,} updates at 0.05 seconds each).",
                f"- Peak active test cars: {peak_cars:,}; active at end: {summary['active_cars_at_end']:,}.",
                f"- Total spawned / completed: {traffic._spawned_count:,} / {total_completed:,}.",
                f"- Target cap at end: {cap:,}; schedule: {cap_description}.",
                f"- Measured update FPS uses the rolling mean wall time of {WINDOW_FRAMES} simulator updates; the threshold is 200 ms/update.",
                f"- Directed portal routes cached before timing: {reachable_portal_pairs}; route setup excluded from the FPS result ({route_precompute_seconds:.2f} seconds).",
                f"- Host: {cpu_name()} ({os.cpu_count()} logical CPUs), {platform.platform()}, Python {platform.python_version()}.",
                f"- Benchmark wall time: {wall_elapsed:.1f} seconds.",
                "",
                "## Network",
                "",
                f"- {network['driveable_ways_used']:,} clipped OSM ways, {network['road_segments']:,} simulation road segments, {network['street_junctions']:,} junctions.",
                f"- {network['network_length_feet'] / 5280:.1f} miles of road centerline; {network['portal_junctions']} city-boundary portals available, {len(portals)} selected.",
                f"- OSM snapshot: {network['osm_snapshot']}; boundary relation: {network['boundary_relation_id']} ({network['boundary_name']}).",
                "",
                "## Update phase timings",
                "",
                f"These are profiler samples across the full {duration:.0f}-second run. Values are milliseconds.",
                "",
                "| Phase | Mean | P95 | P99 | Max |",
                "|---|---:|---:|---:|---:|",
                *phase_rows,
                "",
                "## Internal phase timings across all stages",
                "",
                "| Internal phase | Mean | P95 | P99 | Max |",
                "|---|---:|---:|---:|---:|",
                *overall_detailed_rows,
                "",
                *staged_report,
                "",
                "## Method and limits",
                "",
                f"The test uses the existing `data_first` routed traffic update. Cars spawn from selected Arcata boundary portals, use cached directed routes, and inherit the simulator's 25 mph test-car behavior. Target cap schedule: {cap_description}.",
                "",
                "The input is OpenStreetMap road geometry, not actual vehicle GPS traces. The road extract query box was `40.82,-124.13,40.91,-124.02`; streets wholly outside that extract box in Arcata's far southern area are omitted. Results are for this host, Python build, selected network, and data-first simulator mode.",
                "",
                "© OpenStreetMap contributors, ODbL 1.0. See [OpenStreetMap copyright and attribution](https://www.openstreetmap.org/copyright).",
                "",
            ]
            (out_dir / "report.md").write_text("\n".join(report))

    for frame in range(steps):
        now_simulated = traffic.elapsed_time
        if args.stage_caps:
            cap = cap_for_staged_run(now_simulated, duration, args.stage_caps)
            traffic.max_cars = cap
        elif not threshold_reached and now_simulated + 1e-9 >= next_ramp_at:
            cap += args.ramp_increment
            traffic.max_cars = cap
            next_ramp_at += args.ramp_interval

        started = time.perf_counter()
        completed = traffic.update(city, FRAME_DT)
        completed_frames += 1
        elapsed = time.perf_counter() - started
        total_completed += len(completed)
        active = sum(car.source_type == "test_traffic" for car in traffic.cars)
        peak_cars = max(peak_cars, active)
        rolling.append(elapsed)
        if len(rolling) == WINDOW_FRAMES:
            rolling_fps = 1.0 / statistics.mean(rolling)
            lowest_rolling_fps = min(lowest_rolling_fps, rolling_fps)
            if not threshold_reached and rolling_fps <= FPS_LIMIT:
                threshold_reached = True
                threshold_at = traffic.elapsed_time
                threshold_fps = rolling_fps
                threshold_active_cars = active
                if not args.stage_caps:
                    cap = traffic.max_cars
        bucket.append((elapsed, cap, active, traffic._spawned_count))
        if len(bucket) >= int(round(args.bin_seconds / FRAME_DT)):
            flush_bucket()

        wall_now = time.perf_counter()
        if wall_now - last_heartbeat >= args.heartbeat_seconds:
            sim_fps = 1.0 / statistics.mean(rolling) if rolling else 0.0
            print(
                f"progress sim={traffic.elapsed_time:7.1f}/{duration:.0f}s "
                f"cars={active:5d}/{cap:<5d} "
                f"update_fps={sim_fps:6.2f} "
                f"threshold={'hit' if threshold_reached else 'not yet'} "
                f"wall={wall_now - wall_started:.0f}s",
                flush=True,
            )
            last_heartbeat = wall_now
        if wall_now - last_checkpoint >= args.checkpoint_seconds:
            save_checkpoint()
            last_checkpoint = wall_now

    flush_bucket()
    save_checkpoint(final=True)
    return out_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm", action="append", required=True, help="OSM Overpass JSON extract; repeat to merge adjacent extracts")
    parser.add_argument("--boundary", required=True, help="OSM XML file containing Arcata administrative boundary relation")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION, help="Simulated seconds; default is 900 (15 minutes)")
    parser.add_argument("--initial-cap", type=int, default=40)
    parser.add_argument("--stage-caps", type=parse_stage_caps, default=(), help="Comma-separated active-car caps, held for equal simulated-time stages")
    parser.add_argument("--ramp-increment", type=int, default=40)
    parser.add_argument("--ramp-interval", type=float, default=15.0)
    parser.add_argument("--spawn-interval", type=float, default=0.5)
    parser.add_argument("--portal-count", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20261017)
    parser.add_argument("--bin-seconds", type=float, default=5.0)
    parser.add_argument("--heartbeat-seconds", type=float, default=15.0)
    parser.add_argument("--checkpoint-seconds", type=float, default=30.0)
    parser.add_argument("--label", default=None, help="Use a stable results directory name")
    return parser.parse_args()


if __name__ == "__main__":
    output = run_benchmark(parse_args())
    print(f"Results written to {output}", flush=True)
