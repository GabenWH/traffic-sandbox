"""Build a roundabout out of shared lanes, entrances and exits.

There is deliberately no driving AI here. This module only draws the roads and
connects them. A car entering the circle uses the same yield/gap decision that
another merge can use. A car already on the circle follows ordinary lane traffic.
"""
from math import atan2, cos, sin, pi, ceil, dist

from models import (Lane, LaneConnection, ManeuverDefinition, ManeuverType,
                    ControlDefinition, ControlType)


def ring_radius(junction):
    return junction.radius * 0.65


def _curve(start, end, heading_in, heading_out):
    """A short curved connector that meets both roads pointing the right way."""
    handle = dist(start, end) * 0.35
    a = (start[0] + heading_in[0] * handle, start[1] + heading_in[1] * handle)
    b = (end[0] - heading_out[0] * handle, end[1] - heading_out[1] * handle)
    points = []
    for i in range(13):
        t = i / 12
        u = 1 - t
        points.append(tuple(u**3 * start[k] + 3*u*u*t*a[k] + 3*u*t*t*b[k] + t**3*end[k]
                            for k in (0, 1)))
    return points


def add_roundabout_to_layer(layer, junction):
    """Add one shared ring to the existing routing graph.

    Split the ring at each entrance and exit. Every destination then uses the
    SAME Lane objects for the pieces it travels along. That shared identity is
    what lets a driver see the car ahead, regardless of its eventual exit.
    """
    # Local import avoids making models depend on the routing module.
    from mobility import MobilityLink, road_input_node, road_output_node
    incoming, outgoing = junction.incoming_ports(), junction.outgoing_ports()
    if not incoming or not outgoing:
        return
    cx, cy = junction.position
    radius = ring_radius(junction)
    gates = []
    for role, ports in (("entry", incoming), ("exit", outgoing)):
        for port in ports:
            angle = atan2(-(port.position[1] - cy), port.position[0] - cx)
            # Exit before the nearby entry, so departing traffic frees space.
            angle = (angle + (0.42 if role == "entry" else -0.42)) % (2*pi)
            gates.append((angle, role, port))
    gates.sort(key=lambda gate: (gate[0], gate[1], gate[2].id))

    def point(angle):
        # Screen Y increases downward: minus sin gives counterclockwise traffic.
        return (cx + radius*cos(angle), cy - radius*sin(angle))

    def node(i):
        return ("roundabout_gate", junction.id, i)

    lanes = []
    for i, (angle, role, port) in enumerate(gates):
        next_angle = gates[(i + 1) % len(gates)][0]
        sweep = (next_angle - angle) % (2*pi)
        steps = max(2, ceil(sweep * radius / 3))
        points = [point(angle + sweep*j/steps) for j in range(steps + 1)]
        lane = Lane(f"Roundabout arc {i}", points, points[-1],
                    road_id=f"roundabout:{junction.id}", lane_index=i)
        lanes.append(lane)
        layer.positions[node(i)] = points[0]
        layer.graph.add_edge(node(i), node((i+1) % len(gates)),
                             sum(dist(a, b) for a, b in zip(points, points[1:])),
                             MobilityLink("lane", lane))

    for i, (angle, role, port) in enumerate(gates):
        tangent = (-sin(angle), -cos(angle))
        if role == "entry":
            source = port
            destination = next((p for p in outgoing if p.road is port.road), outgoing[0])
            path = _curve(port.position, point(angle), port.heading, tangent)
            start, end = road_output_node(port), node(i)
        else:
            source = next((p for p in incoming if p.road is port.road), incoming[0])
            destination = port
            path = _curve(point(angle), port.position, tangent, port.heading)
            start, end = node(i), road_input_node(port)
        connection = LaneConnection(
            junction.id, source, destination, path,
            ManeuverDefinition(ManeuverType.MERGE if role == "entry" else ManeuverType.RIGHT_TURN, 0),
            ControlDefinition(ControlType.YIELD if role == "entry" else ControlType.UNCONTROLLED),
            roundabout_role=role,
        )
        # The entry names the ordinary shared lane it joins. Merge behavior
        # needs this target, not any knowledge that the lane belongs to a circle.
        if role == "entry":
            connection.merge_target = ("lane", lanes[i].id)
        layer.graph.add_edge(start, end, connection.length, MobilityLink("lane_connection", connection))
