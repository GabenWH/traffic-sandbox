"""Owner-thread travel observations and commuter habits between simulated days."""
from collections import Counter,defaultdict
from hashlib import blake2b
from math import isfinite


def stable_number(value):
    return int.from_bytes(blake2b(str(value).encode(),digest_size=8).digest(),'little')


class TravelLearning:
    def __init__(self):
        self.estimates={};self.samples={};self.habits={};self.model_day=-1
        self._remaining={};self._users=defaultdict(set)

    def record(self,key,seconds,*,day):
        if not isinstance(key,str) or not key or not isfinite(seconds) or seconds<0 or not isinstance(day,int) or day<0:
            raise ValueError('Invalid travel-time observation')
        bucket=self.samples.setdefault(day,{})
        row=bucket.setdefault(key,[0.,0]);row[0]+=seconds;row[1]+=1

    def costs_for(self,day):
        if not isinstance(day,int) or day<0:raise ValueError('Invalid routing day')
        if day<self.model_day:raise ValueError('Routing day cannot move backward')
        if day>self.model_day:
            for old in sorted(d for d in self.samples if d<day):
                for key,(total,count) in self.samples.pop(old).items():
                    observed=total/count
                    self.estimates[key]=.75*self.estimates.get(key,observed)+.25*observed
            self.model_day=day
        return dict(self.estimates)

    @staticmethod
    def should_switch(driver,old_seconds,new_seconds):
        threshold=.10+(stable_number(driver)%1001)/10000
        return new_seconds<old_seconds*(1-threshold)

    def track(self,vehicle,keys):
        self.finish(vehicle);remaining=Counter(keys);self._remaining[vehicle]=remaining
        for key in remaining:self._users[key].add(vehicle)

    def passed(self,vehicle,key):
        remaining=self._remaining.get(vehicle)
        if remaining and remaining[key]:
            remaining[key]-=1
            if not remaining[key]:
                self._users[key].discard(vehicle)
                if not self._users[key]:del self._users[key]

    def finish(self,vehicle):
        for key in self._remaining.pop(vehicle,{}):
            users=self._users.get(key)
            if users is not None:
                users.discard(vehicle)
                if not users:del self._users[key]

    def affected_vehicles(self,key):return set(self._users.get(key,()))

    def to_dict(self):
        return dict(estimates=dict(self.estimates),model_day=self.model_day,
                    samples=[dict(day=day,links=rows) for day,rows in sorted(self.samples.items())],
                    habits=[dict(key=list(key),plan=plan) for key,plan in self.habits.items()])

    @classmethod
    def from_dict(cls,data):
        result=cls()
        try:
            result.estimates=dict(data.get('estimates',{}));result.model_day=data.get('model_day',-1)
            if not isinstance(result.model_day,int) or result.model_day< -1:raise ValueError('Invalid learned day')
            for key,value in result.estimates.items():
                if not isinstance(key,str) or not isfinite(value) or value<0:raise ValueError('Invalid learned travel time')
            for row in data.get('samples',[]):
                day=row['day']
                if not isinstance(day,int) or day<0:raise ValueError('Invalid observation day')
                links={}
                for key,(total,count) in row['links'].items():
                    if not isinstance(key,str) or not isfinite(total) or total<0 or not isinstance(count,int) or count<=0:
                        raise ValueError('Invalid travel observations')
                    links[key]=[total,count]
                result.samples[day]=links
            for row in data.get('habits',[]):
                key=tuple(row['key']);plan=dict(row['plan'])
                if len(key)!=3 or not all(isinstance(k,str) for k in key):raise ValueError('Invalid familiar route key')
                if not isinstance(plan['day'],int) or not isinstance(plan['edges'],list) or not all(isinstance(k,str) for k in plan['edges']):
                    raise ValueError('Invalid familiar route')
                result.habits[key]=plan
        except (KeyError,TypeError,OverflowError) as error:
            raise ValueError('Invalid route-learning snapshot') from error
        return result
