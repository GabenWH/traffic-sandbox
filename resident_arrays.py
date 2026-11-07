"""Packed resident columns with lightweight compatible Resident views.

Numeric array buffers own all stored fields. Strings are interned once in a
shared code table; no object-dtype arrays or per-resident dictionaries remain.
Views preserve identity for event/trip callers which hold a Resident reference.
"""
import numpy as np
from numpy_storage import NumericColumns
from collections.abc import MutableMapping, ValuesView
from dataclasses import dataclass, asdict


@dataclass(init=False)
class Resident:
    __slots__ = ('_table','_row','_values')
    id: int
    home: str
    worker: bool
    mode: str = 'walk'
    state: str = 'home'
    car_id: str | None = None
    return_due: bool = False
    workplace: str = 'work'
    worksite: str | None = None

    def __init__(self,id,home,worker,mode='walk',state='home',car_id=None,
                 return_due=False,workplace='work',worksite=None):
        self._table=None;self._row=-1
        self._values=dict(id=id,home=home,worker=worker,mode=mode,state=state,
                          car_id=car_id,return_due=return_due,workplace=workplace,worksite=worksite)

    def __deepcopy__(self,memo):
        result=Resident(**asdict(self));memo[id(self)]=result;return result


def _field(name):
    if name=='id':
        def get(person):
            table=person._table
            return person._values[name] if table is None else int(table.columns[name][person._row])
    elif name in ('worker','return_due'):
        def get(person):
            table=person._table
            return person._values[name] if table is None else bool(table.columns[name][person._row])
    else:
        def get(person):
            table=person._table
            return person._values[name] if table is None else table.labels[table.columns[name][person._row]]
    def set(person,value):
        if person._table is None:person._values[name]=value
        else:person._table.write(name,person._row,value)
    return property(get,set)


for _name in Resident.__dataclass_fields__:setattr(Resident,_name,_field(_name))


class _Values(ValuesView):
    def __iter__(self):return (p for p in self._mapping._views if p is not None)


class ResidentTable(MutableMapping):
    """Dense rows, direct lookup for sequential IDs, sparse-ID fallback index.

    Row numbers remain stable on deletion; released rows are reused. All fields
    live in NumPy numeric columns, with vectorized population aggregation.
    """
    flags={'worker','return_due'}
    def __init__(self,residents=()):
        self._storage=NumericColumns({name:np.int64 if name=='id' else np.int8 if name in self.flags else np.int32
                                      for name in Resident.__dataclass_fields__})
        self.labels=[None];self.codes={None:0}
        self._views=[];self._sparse={};self._free=[];self._count=0
        for person in residents:self[person.id]=person

    def __len__(self):return self._count
    def __iter__(self):
        return (int(self.columns['id'][row]) for row,p in enumerate(self._views) if p is not None)
    def values(self):return _Values(self)

    def _row_for(self,key):
        if isinstance(key,bool) or not isinstance(key,int):raise KeyError(key)
        if 0<=key<len(self._views) and self._views[key] is not None and self.columns['id'][key]==key:return key
        try:return self._sparse[key]
        except KeyError:raise KeyError(key) from None

    def __getitem__(self,key):return self._views[self._row_for(key)]

    def _encode(self,name,value):
        if name=='id':
            if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<2**63:
                raise ValueError('Resident ID must be a nonnegative 64-bit integer')
            return value
        if name in self.flags:return int(bool(value))
        if value is not None and not isinstance(value,str):raise ValueError('Resident labels must be strings or None')
        if value not in self.codes:
            self.codes[value]=len(self.labels);self.labels.append(value)
        return self.codes[value]

    def read(self,name,row):
        value=self.columns[name][row]
        return int(value) if name=='id' else bool(value) if name in self.flags else self.labels[value]

    def write(self,name,row,value):
        if name=='id' and value!=self.columns['id'][row]:raise ValueError('Remove and reinsert a resident to change its ID')
        self.columns[name][row]=self._encode(name,value)

    def __setitem__(self,key,person):
        if isinstance(key,bool) or not isinstance(key,int) or not isinstance(person,Resident) or key!=person.id:
            raise ValueError('Resident key must match its integer ID')
        if key in self:
            if self[key] is person:return
        if person._table is not None:raise ValueError('A Resident already belongs to another table')
        data={name:self._encode(name,getattr(person,name)) for name in self.columns}
        if key in self:del self[key]
        if self._free:
            row=self._free.pop()
            for name,value in data.items():self.columns[name][row]=value
            self._views[row]=person
        else:
            row=self._storage.append(data)
            self._views.append(person)
        if key!=row:self._sparse[key]=row
        person._table=self;person._row=row;person._values=None;self._count+=1

    def __delitem__(self,key):
        row=self._row_for(key);person=self._views[row]
        person._values={name:self.read(name,row) for name in self.columns}
        person._table=None;person._row=-1
        self._views[row]=None;self._sparse.pop(key,None);self._free.append(row);self._count-=1
        # Zero codes ensure bulk state counts exclude released rows.
        for column in self.columns.values():column[row]=0

    def state_counts(self):
        counts=np.bincount(self.columns['state'],minlength=len(self.labels))
        return {self.labels[i]:int(n) for i,n in enumerate(counts) if i and n}

    @property
    def columns(self):return self._storage.columns

    @property
    def numeric_bytes(self):return self._storage.nbytes
