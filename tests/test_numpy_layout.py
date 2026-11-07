import gc
import json
import random
import unittest
import weakref
import numpy as np
from event_queue import EventQueue
from numpy_storage import NumericColumns,PackedPoints
from resident_arrays import Resident,ResidentTable
from packed_graph import PackedGraph,PackedPositions
from pathfinding import DirectedGraph
from pedestrian_mobility import WalkLink,PackedWalkLinks,WalkingRoute
from walking_cache import walking_geometry_key


class NumpyLayoutTests(unittest.TestCase):
    def test_resident_buffers_are_numeric_and_growth_preserves_views(self):
        person=Resident(0,'home',True);table=ResidentTable([person])
        for i in range(1,1000):table[i]=Resident(i,'home',False)
        person.state='work'
        self.assertEqual(table.state_counts(),{'home':999,'work':1})
        for values in table.columns.values():
            self.assertIsInstance(values,np.ndarray);self.assertFalse(values.dtype.hasobject)
            self.assertEqual(len(values),1000)
        self.assertEqual(table.columns['state'][0],table.codes['work'])
        json.dumps(table.state_counts())

    def test_packed_event_heap_matches_reference_and_reuses_rows(self):
        rng=random.Random(43);queue=EventQueue();reference={}
        for seq in range(2000):
            key=str(seq);value=rng.choice([None,seq,[seq,seq+1],(seq,seq+1),'household'])
            row=(rng.randrange(100),seq,'event',[key,value])
            queue.push(row);reference[key]=row
            if seq%3==0:
                key=rng.choice(list(reference));self.assertEqual(queue.cancel(key),reference.pop(key))
            if seq%7==0 and reference:
                row=min(reference.values(),key=lambda r:r[:2])
                self.assertEqual(queue.pop_next(),row);del reference[row[3][0]]
        self.assertEqual(sorted(reference.values()),[queue.pop_next() for _ in range(len(queue))])
        self.assertFalse(queue.positions)
        size=queue._storage.size
        for i in range(100):queue.push((i,i,'again',[str(i),i]))
        self.assertEqual(queue._storage.size,size)
        for values in queue._storage.buffers.values():self.assertFalse(values.dtype.hasobject)

    def test_cancelled_heterogeneous_payload_is_released(self):
        class Payload:pass
        queue=EventQueue();payload=Payload();ref=weakref.ref(payload)
        queue.push((1,1,'custom',['custom',payload]));del payload
        queue.cancel('custom');gc.collect()
        self.assertIsNone(ref());self.assertFalse(queue._objects)

    def test_point_views_share_storage_and_keep_exact_geometry_keys(self):
        raw=[(0.,-0.),(1.25,2.5),(3.,4.)];points=PackedPoints(raw)
        self.assertEqual(points,raw);self.assertEqual(points[::-1],raw[::-1])
        self.assertTrue(np.shares_memory(points.data,points[1:].data))
        self.assertEqual(walking_geometry_key(points,.5),walking_geometry_key(raw,.5))
        self.assertEqual(walking_geometry_key(points[::-1],-.1),walking_geometry_key(raw[::-1],-.1))
        with self.assertRaises(ValueError):points.data[0]=[9,9]
        from models import polyline_length
        from math import dist
        expected=sum(dist(a,b) for a,b in zip(raw,raw[1:]))
        self.assertEqual(polyline_length(points),expected)
        self.assertEqual(polyline_length(points),expected)
        self.assertEqual(points[::-1].length(),expected)

    def test_packed_graph_preserves_edge_order_costs_and_editing(self):
        old=DirectedGraph();old.add_edge('a','b',1,'ab');old.add_edge('b','c',2,'bc');old.add_edge('a','c',5,'ac')
        packed=PackedGraph(old)
        self.assertEqual(old.find_path('a','c'),packed.find_path('a','c'))
        self.assertEqual(old.transitions_from('a'),packed.transitions_from('a'))
        self.assertIsNone(packed._builder)
        packed.add_edge('a','c',.5,'shortcut')
        self.assertEqual(packed.find_path('a','c').edges,('shortcut',))
        positions=PackedPositions({'a':(0,0),'b':(1,1)})
        self.assertEqual(dict(positions),{'a':(0.,0.),'b':(1.,1.)})
        positions['a']=(2,3);self.assertEqual(positions['a'],(2,3))

    def test_walking_links_pack_ragged_shapes_without_retaining_leg_objects(self):
        original=[WalkLink('lane',((0,0),(1,0))),WalkLink('junction',((1,0),(2,1),(3,1)))]
        packed=PackedWalkLinks(original)
        self.assertEqual([(x.kind,tuple(x.points)) for x in packed],[(x.kind,x.points) for x in original])
        self.assertEqual(packed.points.shape,(5,2));self.assertFalse(packed.points.dtype.hasobject)
        route=WalkingRoute(((0,0),(1,0)),(),1.,-1.)
        self.assertIsInstance(route.points,PackedPoints)
        self.assertEqual(len(route.links),0)
