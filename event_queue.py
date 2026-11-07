"""Indexed NumPy event heap with packed common payloads and O(log n) removal."""
import numpy as np
from numpy_storage import NumericColumns


class EventQueue:
    def __init__(self,rows=()):
        self._storage=NumericColumns(dict(time=np.float64,sequence=np.int64,kind=np.int32,
            tag=np.int8,a=np.int64,b=np.int64,heap=np.int32,position=np.int32))
        self._count=0
        self.positions={}  # Active cancellation key -> stable numeric row.
        self._keys=[];self._free=[]
        self._kinds=[];self._kind_ids={}
        self._labels=[];self._label_ids={}
        self._objects={}  # Uncommon heterogeneous service payloads only.
        for row in rows:self.push(tuple(row))

    def __len__(self):return self._count
    def __iter__(self):return (self._decode(int(slot)) for slot in self._storage.buffers['heap'][:self._count])
    def __getitem__(self,index):
        if isinstance(index,slice):return list(self)[index]
        if index<0:index+=self._count
        if not 0<=index<self._count:raise IndexError(index)
        return self._decode(int(self._storage.buffers['heap'][index]))
    def clear(self):self.__init__()
    @property
    def rows(self):return list(self)
    @staticmethod
    def key(row):return row[3][0]

    def _encode(self,value):
        if value is None:return 0,0,0
        if type(value) is int and -(2**63)<=value<2**63:return 1,value,0
        if isinstance(value,str):
            if value not in self._label_ids:
                self._label_ids[value]=len(self._labels);self._labels.append(value)
            return 2,self._label_ids[value],0
        if isinstance(value,(list,tuple)) and len(value)==2 and all(type(v) is int and -(2**63)<=v<2**63 for v in value):
            return (3 if isinstance(value,list) else 4),value[0],value[1]
        return 5,0,0

    def _decode(self,slot):
        columns=self._storage.buffers
        tag=int(columns['tag'][slot]);a=int(columns['a'][slot]);b=int(columns['b'][slot])
        value=(None if tag==0 else a if tag==1 else self._labels[a] if tag==2
               else [a,b] if tag==3 else (a,b) if tag==4 else self._objects[slot])
        return (float(columns['time'][slot]),int(columns['sequence'][slot]),
                self._kinds[int(columns['kind'][slot])],[self._keys[slot],value])

    def _before(self,a,b):
        columns=self._storage.buffers;times=columns['time'];sequence=columns['sequence']
        return times[a]<times[b] or (times[a]==times[b] and sequence[a]<sequence[b])

    def _swap(self,a,b):
        heap=self._storage.buffers['heap'];positions=self._storage.buffers['position']
        x,y=int(heap[a]),int(heap[b]);heap[a],heap[b]=y,x
        positions[x],positions[y]=b,a

    def _up(self,i):
        heap=self._storage.buffers['heap']
        while i and self._before(int(heap[i]),int(heap[(i-1)//2])):
            parent=(i-1)//2;self._swap(i,parent);i=parent
        return i

    def _down(self,i):
        heap=self._storage.buffers['heap']
        while 2*i+1<self._count:
            child=2*i+1
            if child+1<self._count and self._before(int(heap[child+1]),int(heap[child])):child+=1
            if not self._before(int(heap[child]),int(heap[i])):break
            self._swap(i,child);i=child

    def push(self,row):
        key=self.key(row)
        if key in self.positions:raise ValueError('Duplicate event key: '+str(key))
        when,sequence,kind,(_,value)=row
        tag,a,b=self._encode(value)
        if kind not in self._kind_ids:
            self._kind_ids[kind]=len(self._kinds);self._kinds.append(kind)
        data=dict(time=when,sequence=sequence,kind=self._kind_ids[kind],tag=tag,a=a,b=b,position=self._count)
        if self._free:
            slot=self._free.pop()
            for name,v in data.items():self._storage.buffers[name][slot]=v
            self._keys[slot]=key
        else:
            slot=self._storage.append(data);self._keys.append(key)
        if tag==5:self._objects[slot]=value
        self.positions[key]=slot
        self._storage.buffers['heap'][self._count]=slot;self._count+=1
        self._up(self._count-1)

    def cancel(self,key):
        slot=self.positions.pop(key,None)
        if slot is None:return None
        row=self._decode(slot);i=int(self._storage.buffers['position'][slot])
        heap=self._storage.buffers['heap'];last=int(heap[self._count-1]);self._count-=1
        if i<self._count:
            heap[i]=last;self._storage.buffers['position'][last]=i
            self._down(self._up(i))
        self._keys[slot]=None;self._objects.pop(slot,None);self._free.append(slot)
        return row

    def pop_next(self):return self.cancel(self._keys[int(self._storage.buffers['heap'][0])])
