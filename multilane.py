"""Derived lane interfaces; saved junction policies remain road-to-road."""
from math import hypot
from models import RoadPort, RoadPortFlow, LaneConnection, ManeuverType, _connection_path, _cul_de_sac_connection_path


class LanePort(RoadPort):
    @property
    def id(self):
        return f'{super().id}:lane:{self.lanes[0].lane_index}'

    @property
    def key(self):
        return (*super().key, self.lanes[0].lane_index)


def outside_lanes(port):
    return sorted(port.lanes, key=lambda lane: lane.lane_index,
                  reverse=port.lanes[0].direction == 'forward')


def lane_ports(port):
    if len(port.lanes) == 1:
        return (port,)
    result = []
    for lane in outside_lanes(port):
        entering = port.flow is RoadPortFlow.INPUT
        a, b = lane.points[:2] if entering else lane.points[-2:]
        length = hypot(b[0]-a[0], b[1]-a[1])
        result.append(LanePort(port.road, port.end, port.flow,
                              lane.points[0] if entering else lane.points[-1],
                              ((b[0]-a[0])/length, (b[1]-a[1])/length),
                              port.road.lane_width, (lane,)))
    return tuple(result)


def lane_connections(connection):
    """Keep inner lanes aligned; surplus outside lanes merge into the last lane."""
    sources = tuple(reversed(lane_ports(connection.source_output)))
    targets = tuple(reversed(lane_ports(connection.destination_input)))
    if len(sources) == len(targets) == 1:
        return (connection,)
    pairs = [(s, targets[min(i, len(targets)-1)]) for i, s in enumerate(sources)]
    # At a widening, each new lane must also be reachable from the outer lane.
    pairs.extend((sources[-1], t) for t in targets[len(sources):])
    result = []
    for source, target in pairs:
        path = (_cul_de_sac_connection_path(source, target, source.road.lane_width*2)
                if connection.maneuver.kind is ManeuverType.U_TURN else _connection_path(source, target))
        derived = LaneConnection(connection.intersection_id, source, target,
                                 path, connection.maneuver,
                                 connection.control)
        derived._policy_source = connection
        if sum(t.id == target.id for _, t in pairs) > 1:
            derived.merge_target = ('lane', target.lanes[0].id)
        result.append(derived)
    return tuple(result)
