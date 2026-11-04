"""Repeatable shift offsets and owner-thread departure admission limits."""
from dataclasses import asdict,dataclass
from math import isfinite
from route_learning import stable_number


@dataclass(frozen=True)
class CommutePolicy:
    departure_window: float=7200.
    starts_per_second: float=20.
    burst: int=4
    cars_per_entrance_per_second: float=1.
    max_active_vehicles: int=2000
    checks_per_update: int=32
    route_submissions: int=4
    route_pending: int=128

    def __post_init__(self):
        if not isfinite(self.departure_window) or not 0<=self.departure_window<=21600:
            raise ValueError('Departure window must be finite and within six hours')
        for value in (self.starts_per_second,self.cars_per_entrance_per_second):
            if not isfinite(value) or value<=0 or not isfinite(1/value):raise ValueError('Departure rates must be positive and finite')
        for value in (self.burst,self.max_active_vehicles,self.checks_per_update,self.route_submissions,self.route_pending):
            if isinstance(value,bool) or not isinstance(value,int) or value<1:raise ValueError('Departure limits must be positive integers')

    def offset(self,person,workplace):
        half=self.departure_window/2
        return half*((stable_number(workplace)%1000000)/1000000+(stable_number(person)%1000000)/1000000)


class DepartureLimits:
    def __init__(self,policy):
        self.policy=policy;self.tokens=float(policy.burst);self.time=0.;self.entrances={}

    def _refill(self,now):
        self.tokens=min(float(self.policy.burst),self.tokens+max(0.,now-self.time)*self.policy.starts_per_second)
        self.time=max(self.time,now)

    def available(self,now,entrance=None,active=None):
        self._refill(now)
        return (self.tokens>=1-1e-8 and (active is None or active<self.policy.max_active_vehicles)
                and (entrance is None or now+1e-8>=self.entrances.get(entrance,0.)))

    def consume(self,now,entrance=None):
        self._refill(now);self.tokens=max(0.,self.tokens-1)
        if entrance is not None:self.entrances[entrance]=now+1/self.policy.cars_per_entrance_per_second

    def to_dict(self):
        return dict(tokens=self.tokens,time=self.time,entrances=[(key,value) for key,value in self.entrances.items()])

    @classmethod
    def from_dict(cls,policy,data):
        result=cls(policy)
        try:
            result.tokens=float(data['tokens']);result.time=float(data['time'])
            result.entrances={tuple(key):float(value) for key,value in data['entrances']}
            if not 0<=result.tokens<=policy.burst or not isfinite(result.time) or result.time<0:
                raise ValueError('Invalid saved departure budget')
            if any(len(k)!=2 or not all(isinstance(p,str) for p in k) or not isfinite(v) or v<0 for k,v in result.entrances.items()):
                raise ValueError('Invalid saved entrance budget')
        except (KeyError,TypeError,OverflowError) as error:raise ValueError('Invalid departure limits') from error
        return result
