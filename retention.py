"""Small explicit bounds for reusable paths and diagnostic event history."""
from collections import OrderedDict

class BoundedCache(OrderedDict):
    def __init__(self,*args,max_entries=4096,**kwargs):
        self.max_entries=max_entries
        super().__init__(*args,**kwargs)

    def __getitem__(self,key):
        value=super().__getitem__(key);self.move_to_end(key);return value

    def __setitem__(self,key,value):
        super().__setitem__(key,value);self.move_to_end(key)
        while len(self)>self.max_entries:self.popitem(last=False)

class EventHistory(list):
    """Keep recent diagnostics; discard an amortized batch on overflow."""
    limit=8192
    def append(self,value):
        super().append(value)
        if len(self)>self.limit:del self[:max(1,self.limit//8)]
