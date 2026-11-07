"""Owned numeric buffers and immutable point sequences; no object-dtype arrays."""
from collections.abc import Sequence
from math import dist
import numpy as np


class NumericColumns:
    """Geometrically grown columns with stable row indices.

    ``columns`` exposes live rows only. Reacquire a view after inserting rows:
    growing capacity can replace the backing allocation.
    """
    def __init__(self,dtypes):
        self.dtypes={k:np.dtype(v) for k,v in dtypes.items()}
        if any(t.hasobject for t in self.dtypes.values()):raise ValueError('Numeric columns cannot own Python objects')
        self.size=self.capacity=0
        self.buffers={k:np.empty(0,dtype=t) for k,t in self.dtypes.items()}
        self.columns=dict(self.buffers)

    def append(self,values):
        if self.size==self.capacity:
            capacity=max(64,self.capacity*2)
            for name,dtype in self.dtypes.items():
                grown=np.zeros(capacity,dtype=dtype)
                grown[:self.size]=self.buffers[name][:self.size]
                self.buffers[name]=grown
            self.capacity=capacity
        row=self.size
        for name,value in values.items():self.buffers[name][row]=value
        self.size+=1
        self.columns={name:values[:self.size] for name,values in self.buffers.items()}
        return row

    @property
    def nbytes(self):return sum(a.nbytes for a in self.columns.values())


class PackedPoints(Sequence):
    """Float64 Nx2 storage with tuple-compatible scalar reads and truth tests."""
    __slots__=('data','_length')
    def __init__(self,points):
        self._length=None
        if isinstance(points,PackedPoints):self.data=points.data;self._length=points._length;return
        data=np.array(points,dtype=np.float64,copy=True)
        if not data.size:data=data.reshape(0,2)
        if data.ndim!=2 or data.shape[1]!=2:raise ValueError('Point buffers require an Nx2 shape')
        data.flags.writeable=False
        self.data=data

    @classmethod
    def _view(cls,data):
        result=object.__new__(cls);result.data=data;result._length=None;return result
    def __len__(self):return len(self.data)
    def length(self):
        # Use the original operation order for exact geometry parity. Immutable
        # storage makes the cached ruler valid until the geometry is replaced.
        if self._length is None:self._length=sum(dist(a,b) for a,b in zip(self,self[1:]))
        return self._length
    def __iter__(self):return ((float(p[0]),float(p[1])) for p in self.data)
    def __getitem__(self,index):
        if isinstance(index,slice):return self._view(self.data[index])
        p=self.data[index];return float(p[0]),float(p[1])
    def __eq__(self,other):
        try:return bool(np.array_equal(self.data,np.asarray(other,dtype=np.float64).reshape(-1,2)))
        except (TypeError,ValueError):return False
    def __hash__(self):return hash(tuple(self))
    def __add__(self,other):return PackedPoints(np.concatenate((self.data,np.asarray(other).reshape(-1,2))))
    def __radd__(self,other):return PackedPoints(np.concatenate((np.asarray(other).reshape(-1,2),self.data)))
    def __deepcopy__(self,memo):return self
    def __array__(self,dtype=None,copy=None):
        if copy is False and dtype is not None and np.dtype(dtype)!=self.data.dtype:
            raise ValueError('Requested dtype requires a copy')
        result=self.data if dtype is None else self.data.astype(dtype,copy=False)
        return result.copy() if copy else result


def packed_points(points):
    return points if isinstance(points,PackedPoints) else PackedPoints(points)
