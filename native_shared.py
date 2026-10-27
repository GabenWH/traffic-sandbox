"""Experimental read-through views of the C++ engine's actual vehicle fields.

No IPC segment is needed: ctypes loads the engine into Python's process. C++
alone writes during a step, and Python reads between steps. A view is attached
once at admission, then materialized before its native storage is released.
"""
import ctypes as C

from car_brain import CarBrain
from native_traffic import _SharedVehicle, STATES, SIGNALS
from traffic_testbed import RoutedRoadVehicle


def _property(name, read):
    def set_value(instance, value):
        # Public Python writes remain explicit inputs: preserve all live state
        # before discarding the backend, then reimport it on the next update.
        instance._shared_binding.controller.sim._discard_native()
        setattr(instance, name, value)

    return property(read, set_value)


class SharedRoadVehicle(RoutedRoadVehicle):
    distance = _property('distance', lambda c: c._shared_binding.motion.distance)
    speed = _property('speed', lambda c: c._shared_binding.motion.speed)
    position = _property('position', lambda c: (c._shared_binding.position.x, c._shared_binding.position.y))
    heading = _property('heading', lambda c: (c._shared_binding.heading.x, c._shared_binding.heading.y))
    _merge_entry_speed = _property('_merge_entry_speed', lambda c: None if c._shared_binding.motion.entry < 0 else c._shared_binding.motion.entry)
    _claimed_movement = _property('_claimed_movement', lambda c: c._shared_binding.claim())


class SharedCarBrain(CarBrain):
    _yellow_movement_id = _property('_yellow_movement_id', lambda c: c._shared_binding.yellow())
    _yellow_go = _property('_yellow_go', lambda c: c._shared_binding.yellow_go.value)
    state = _property('state', lambda c: STATES[c._shared_binding.motion.state])
    signal_intent = _property('signal_intent', lambda c: SIGNALS[c._shared_binding.motion.signal])
    desired_speed = _property('desired_speed', lambda c: c._shared_binding.motion.desired)
    stopped_elapsed = _property('stopped_elapsed', lambda c: c._shared_binding.motion.dwell)
    wait_reason = _property('wait_reason', lambda c: c._shared_binding.text(0))
    phantom_target = _property('phantom_target', lambda c: c._shared_binding.text(1))


CAR_FIELDS = ('distance', 'speed', 'position', 'heading', '_merge_entry_speed', '_claimed_movement')
BRAIN_FIELDS = ('state', 'signal_intent', 'desired_speed', 'stopped_elapsed', 'wait_reason', 'phantom_target', '_yellow_movement_id', '_yellow_go')


class SharedBinding:
    def __init__(self, controller, car, handle):
        self.controller, self.car, self.handle = controller, car, handle
        self.engine = controller.engine
        self.car_class, self.brain_class = type(car), type(car.brain)
        if self.car_class is not RoutedRoadVehicle or self.brain_class is not CarBrain:
            raise TypeError('Shared-memory experiment requires standard vehicle and brain types')
        view = _SharedVehicle()
        self.engine._call('nt_shared_vehicle', handle, C.byref(view))
        self.motion, self.position, self.heading = view.motion.contents, view.position.contents, view.heading.contents
        self.claim_index = view.claim.contents
        self.yellow_movement, self.yellow_go = view.yellow_movement.contents, view.yellow_go.contents
        car._shared_binding = car.brain._shared_binding = self
        car.__class__, car.brain.__class__ = SharedRoadVehicle, SharedCarBrain
        self.engine._shared_bindings[handle] = self

    def text(self, field):
        result = self.engine._lib.nt_shared_text(self.engine._ptr, self.handle, field)
        if result is None:
            raise RuntimeError(self.engine._lib.nt_error().decode())
        return result.decode()

    def yellow(self):
        index = self.yellow_movement.value
        return None if index < 0 else self.engine._connections[index].id

    def claim(self):
        index = self.claim_index.value
        return None if index < 0 else self.engine._connections[index]

    def detach(self):
        car = self.car
        values = {name: getattr(car, name) for name in CAR_FIELDS}
        brain_values = {name: getattr(car.brain, name) for name in BRAIN_FIELDS}
        car.__class__, car.brain.__class__ = self.car_class, self.brain_class
        car.__dict__.update(values)
        car.brain.__dict__.update(brain_values)
        del car._shared_binding, car.brain._shared_binding
        self.engine._shared_bindings.pop(self.handle)


def completed_views(controller):
    e = controller.engine
    count = C.c_int()
    rows = e._lib.nt_completed(e._ptr, C.byref(count))
    if count.value < 0:
        raise RuntimeError(e._lib.nt_error().decode())
    completed = []
    for i in range(count.value):
        binding = e._shared_bindings[rows[i].handle]
        completed.append(binding.car)
        binding.detach()
    return completed
