"""Traffic observations and driver-selected strategies for merging.

A merge is described by its target lane, not by the shape of the road. We look
at the routes of nearby cars to find who will reach that lane first. This also
looks through preceding connected sections without getting stuck in a loop:
we inspect only the finite, planned route and only a short distance ahead.
"""

MERGE_HEADWAY_SECONDS = 2.0
MERGE_LOOKBACK = 180.0  # Model distances are feet, like the rest of the simulator.


def merge_has_gap(car, movement, cars, following_gap=22.0):
    """Legacy compatibility check; routed cars no longer call this helper.

    The active path is observe_merge -> CarBrain -> its selected strategy.
    Kept for callers of the first roundabout version, not as a global veto.
    """
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

# The records below contain observations, not permissions. CarBrain owns the
# choice of strategy. Distances use a shared ruler: zero is the joining point,
# negative is upstream, positive is downstream. There are no world-X assumptions.
from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class MergeVehicle:
    id: str
    position: float
    speed: float
    length: float


@dataclass(frozen=True)
class MergeObservation:
    distance_to_join: float
    length: float
    vehicles: tuple[MergeVehicle, ...]


@dataclass(frozen=True)
class MergeChoice:
    desired_speed: float
    can_enter: bool
    reason: str = ""
    phantom_target: str = ""


def observe_merge(car, movement, cars):
    """Translate nearby traffic into distances along the joining lane.

    Through traffic approaching on a previous section gets a negative position.
    Traffic already past the join gets a positive position. Also inspect later
    shared sections: a short first arc must not hide the leader on the next arc.
    """
    _, end, connection = movement
    target = connection.merge_target
    if target is None:
        return None
    vehicles = []
    # A fixed 180-foot window is adequate at roundabout speeds but too short
    # for a fast freeway. Scale the same observation query with traffic speed.
    look_distance = max(MERGE_LOOKBACK, 8.0*max([car.speed, *(other.speed for other in cars)]))
    downstream = [(a, b, key, offset) for a, b, key, offset in car.route_segments
                  if a >= end - 1e-8 and a <= end + look_distance]
    for other in cars:
        if other is car:
            continue
        # Waiting entrants must yield to through traffic, not to each other's
        # imagined future positions. Actual entry claims prevent double entry.
        if any(m[2].merge_target == target and other.distance < m[0]
               for m in other.controlled_movements):
            continue
        position = None
        for a, b, key, offset in other.route_segments:
            if key == target and other.distance <= a:
                position = other.distance - a
                break
        if position is None:
            occupancy = other.occupancy_position()
            if occupancy is not None:
                for a, b, key, offset in downstream:
                    if key == occupancy[0]:
                        position = a - end + occupancy[1] - offset
                        break
        if position is not None and abs(position) <= look_distance:
            vehicles.append(MergeVehicle(other.id, position, other.speed, other.length))
    return MergeObservation(max(0.0, end-car.distance), car.length, tuple(vehicles))


def _arrival_time(distance, speed, desired):
    """Predict travel with the same acceleration limits used by the simulator.

    Unlike dividing by an invented minimum speed, a stopped car takes time to
    accelerate. If the chosen speed is zero, there is no planned rolling entry.
    """
    if distance <= 0:
        return 0.0
    if desired <= 0.01:
        return float('inf')
    acceleration = 10.0 if desired >= speed else -24.0
    change_time = (desired-speed)/acceleration
    change_distance = (speed+desired)*change_time/2
    if distance <= change_distance:
        return (sqrt(max(0.0, speed*speed+2*acceleration*distance))-speed)/acceleration
    return change_time + (distance-change_distance)/desired


def _gap_at_arrival(observation, speed, desired, headway):
    """Check space both ahead AND behind at our predicted joining time.

    The rear gap uses the circulating driver's speed. An entrant cannot claim
    a gap that only works if that driver suddenly brakes to accommodate it.
    """
    # The curved paths become close BEFORE their centerlines meet. Protect
    # the whole joining interval, from the nose approaching shared pavement
    # until the rear has cleared the join, rather than one instant at a point.
    begin = _arrival_time(max(0.0, observation.distance_to_join-observation.length), speed, desired)
    finish = _arrival_time(observation.distance_to_join+observation.length/2, speed, desired)
    if finish == float('inf'):
        return False
    for other in observation.vehicles:
        allowance = (observation.length+other.length)/2 + 4.0
        if other.position + other.speed*begin >= allowance + headway*desired:
            continue
        # A circulating car may accelerate out of a queue while we are joining.
        # Check that possibility, rather than assuming its current low speed
        # stays constant and accepting a gap that immediately disappears.
        cap = max(other.speed, speed, desired)
        accelerating = min(finish, (cap-other.speed)/10.0)
        travel = (other.speed*accelerating + 5*accelerating**2
                  + cap*(finish-accelerating))
        if other.position + travel > -(allowance + headway*cap):
            return False
    return True


class CautiousMerge:
    """Keep the old wait-for-a-generous-opening behavior as a driver choice."""
    def decide(self, observation, speed, cruise):
        clear = _gap_at_arrival(observation, speed, cruise, 2.0)
        return MergeChoice(cruise, clear, "" if clear else "waiting for a generous merge gap")


class RollingMerge:
    """Adapt the original demo's phantom following to connected lane distances.

    Project a circulating car onto our distance ruler. As we approach the join,
    gradually react to its spacing and speed as if it were our leader. We can
    slow toward a gap while still driving down the entrance. The separate gap
    check is retained to ensure there is room behind us as well as ahead.
    """
    def decide(self, observation, speed, cruise):
        desired = cruise
        target = ""
        distance = observation.distance_to_join
        progress = max(0.0, min(1.0, 1.0-distance/128.0))
        strength = progress*progress*(3.0-2.0*progress)
        arrival = _arrival_time(distance, speed, cruise)
        leaders = [other for other in observation.vehicles
                   if other.position + other.speed*arrival >= 0]
        if leaders:
            leader = min(leaders, key=lambda other: other.position + other.speed*arrival)
            target = leader.id
            # Same spacing + relative-speed response as the first demo, with
            # feet along connected lanes replacing the original screen X.
            gap = leader.position + distance - (observation.length+leader.length)/2
            wanted = 6.0 + 0.8*speed
            response = 0.8*(gap-wanted) + 1.2*(leader.speed-speed)
            desired = min(cruise, max(0.0, speed+response*strength))
            if leader.speed > 0.1:
                # Aim to reach the shared pavement after the leader, rather
                # than repeatedly braking at the yield line awaiting permission.
                opening_time = max(0.0, (18.0 + 0.8*speed - leader.position)/leader.speed)
                if opening_time > 0:
                    pace = max(0.0, distance-observation.length)/opening_time
                    desired = min(desired, pace)
        clear = _gap_at_arrival(observation, speed, desired, 0.8)
        reason = "matching speed behind phantom car" if target and desired < cruise else ""
        if not clear:
            reason = "yielding until the merge gap opens"
        return MergeChoice(desired, clear, reason, target)


MERGE_STRATEGIES = {'rolling': RollingMerge(), 'cautious': CautiousMerge()}
