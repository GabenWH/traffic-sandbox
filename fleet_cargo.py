"""A vehicle's ordinary cargo dictionary with presentation edit notification."""
import weakref

_MISSING=object()


class VehicleCargo(dict):
    def __init__(self,values=(),owner=None):
        super().__init__(values)
        self._owner=weakref.ref(owner) if owner is not None else None

    def _changed(self):
        owner=self._owner() if self._owner is not None else None
        if owner is not None and owner.cargo is self:
            callback=owner.__dict__.get('_on_fleet_change')
            if callback is not None:callback(owner.id)

    def __setitem__(self,key,value):
        previous=self.get(key,_MISSING);super().__setitem__(key,value)
        if previous!=value:self._changed()

    def __delitem__(self,key):super().__delitem__(key);self._changed()
    def clear(self):
        if self:super().clear();self._changed()
    def pop(self,key,default=_MISSING):
        existed=key in self
        value=super().pop(key) if default is _MISSING else super().pop(key,default)
        if existed:self._changed()
        return value
    def popitem(self):
        value=super().popitem();self._changed();return value
    def setdefault(self,key,default=None):
        if key not in self:self[key]=default
        return self[key]
    def update(self,*args,**kwargs):
        incoming=dict(*args,**kwargs)
        changed=any(self.get(k,_MISSING)!=v for k,v in incoming.items())
        super().update(incoming)
        if changed:self._changed()
    def __ior__(self,other):self.update(other);return self
