import unittest
from town_simulation import build_town
from town_services import ServiceTown, Business


class ServicesTests(unittest.TestCase):
    def town(self):
        t=build_town(12,work_start=60,work_end=3600)
        t.__class__=ServiceTown
        t.configure_services([Business('work','bakery',{'grain':1},'food',6,{'grain':100})])
        return t

    def test_production_requires_arrived_workers_and_inputs(self):
        t=self.town();s=t.sites['work']['building'].inventory.amounts
        initial=s.get('food',0);t._economy(60);self.assertEqual(s.get('food',0),initial)
        p=next(p for p in t.residents.values() if p.worker);p.state='work'
        t._economy(600);self.assertGreater(s['food'],initial)
        s['grain']=0;before=s['food'];t._economy(600);self.assertEqual(s['food'],before)

    def test_clinic_requires_staff_and_medicine(self):
        t=self.town();t.configure_services([Business('work','clinic',{},None,0,{'medicine':5})])
        patient=next(p for p in t.residents.values() if not p.worker)
        patient.state='waiting_care';t.care_queue.append(patient.id)
        t.sites['work']['building'].inventory.amounts['medicine']=0
        t._economy(300);self.assertEqual(t.treated,0)
        doctor=next(p for p in t.residents.values() if p.worker);doctor.state='work'
        t._economy(300);self.assertEqual(t.treated,0)
        t.sites['work']['building'].inventory.amounts['medicine']=1
        t._economy(300);self.assertEqual(t.treated,1)
        self.assertEqual(t.sites['work']['building'].inventory.amounts['medicine'],0)

    def test_quiescent_service_checkpoint_keeps_businesses_and_requests(self):
        import json
        t=self.town()
        t.requests=[dict(site='work',resource='grain',amount=10)]
        saved=json.loads(json.dumps(t.checkpoint()))
        restored=ServiceTown.from_checkpoint(saved)
        self.assertEqual(restored.report(),t.report())
        self.assertEqual(restored.businesses['work'].inputs,{'grain':1})
        self.assertEqual(restored.requests,t.requests)
