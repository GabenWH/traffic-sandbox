"""Gap acceptance shared by roundabout entrances and future freeway merges.

A merge is described by its target lane, not by the shape of the road. We look
at the routes of nearby cars to find who will reach that lane first. This also
looks through preceding connected sections without getting stuck in a loop:
we inspect only the finite, planned route and only a short distance ahead.
"""

MERGE_HEADWAY_SECONDS = 2.0
MERGE_LOOKBACK = 180.0  # Model distances are feet, like the rest of the simulator.


def merge_has_gap(car, movement, cars, following_gap=22.0):
    """Can our car join the target lane without cutting off approaching traffic?"""
    start, end, connection = movement
    target = connection.merge_target
    if target is None:
        return True
    # Our nose enters first; allow time for the entire car to reach the ring.
    join_time = max(0.0, end - car.distance + car.length / 2) / max(car.speed, 10.0)
    for other in cars:
        if other is car:
            continue
        # Another waiting entrance does not count as priority traffic. Shared
        # conflict claims arbitrate those entrances. A car on the through lane
        # already has priority, including one just upstream of this lane piece.
        waiting_merge = any(
            m[2].merge_target == target and other.distance < m[0]
            for m in other.controlled_movements
        )
        if waiting_merge:
            continue
        for a, b, key, offset in other.route_segments:
            if key != target or other.distance - other.length / 2 > b:
                continue
            distance = a - other.distance
            if distance > MERGE_LOOKBACK:
                continue
            if distance < 0:
                # Already on the target lane: leave enough room in front of us.
                if -distance < following_gap + (car.length + other.length) / 2:
                    return False
            elif distance < following_gap + (car.length + other.length) / 2:
                return False
            elif other.speed > 0.1 and distance / other.speed < join_time + MERGE_HEADWAY_SECONDS:
                return False
    return True
