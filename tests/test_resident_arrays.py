import copy
import unittest
from dataclasses import asdict
from resident_arrays import Resident,ResidentTable


class ResidentArrayTests(unittest.TestCase):
    def test_fields_live_in_numeric_buffers_and_keep_external_view_identity(self):
        p=Resident(0,'home',True,workplace=None);table=ResidentTable([p])
        self.assertIs(table[0],p);self.assertIsNone(p._values)
        self.assertFalse(hasattr(p,'__dict__'))
        p.state='commuting';p.workplace='job';p.return_due=True
        self.assertEqual(table.columns['state'][0],table.codes['commuting'])
        self.assertEqual(table.columns['workplace'][0],table.codes['job'])
        self.assertEqual(table.columns['return_due'][0],1)
        self.assertEqual(asdict(p),dict(id=0,home='home',worker=True,mode='walk',
            state='commuting',car_id=None,return_due=True,workplace='job',worksite=None))

    def test_sparse_ids_do_not_require_sparse_storage(self):
        people=[Resident(i,'home',False) for i in (2**40,7,0)]
        table=ResidentTable(people)
        self.assertEqual(len(table.columns['id']),3)
        for p in people:self.assertIs(table[p.id],p)
        self.assertEqual(list(table),[2**40,7,0])
        self.assertNotIn(True,table)

    def test_deletion_detaches_held_views_and_reuses_rows_safely(self):
        a=Resident(0,'a',True);b=Resident(1,'b',False,state='work')
        table=ResidentTable([a,b]);del table[0]
        self.assertEqual(a.home,'a');a.state='work'
        c=Resident(100,'c',True);table[100]=c
        self.assertEqual(len(table.columns['id']),2)
        self.assertEqual(table.state_counts(),{'home':1,'work':1})
        self.assertEqual(c.home,'c');self.assertNotIn(0,table)
        self.assertIs(table[1],b)

    def test_serialization_and_copy_remain_plain_python_values(self):
        import json
        table=ResidentTable([Resident(0,'home',True,car_id='car',workplace=None)])
        p=table[0];cloned=copy.deepcopy(p)
        self.assertEqual(asdict(p),json.loads(json.dumps(asdict(p))))
        self.assertEqual(p,cloned);cloned.state='work'
        self.assertEqual(p.state,'home')
        self.assertIsNone(cloned._table)

    def test_dense_lookup_has_no_per_resident_hash_index(self):
        table=ResidentTable(Resident(i,'same-home',True) for i in range(16000))
        self.assertEqual(table._sparse,{})
        self.assertEqual(table.numeric_bytes,16000*34)
        self.assertEqual(table.state_counts(),{'home':16000})
        self.assertEqual(table.labels.count('same-home'),1)

    def test_replacement_and_invalid_writes_preserve_consistency(self):
        table=ResidentTable([Resident(0,'home',True)])
        table[0]=Resident(0,'new',False)
        self.assertEqual(table[0].home,'new');self.assertEqual(len(table),1)
        with self.assertRaises(ValueError):table[0].id=1
        with self.assertRaises(ValueError):table[True]=Resident(1,'bad',False)
        self.assertEqual(table[0].id,0)
