import importlib.util
import json
import unittest


class RouteLearningTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('route_learning'),'Following-day route learning is missing')

    def test_observations_apply_only_on_following_days(self):
        from route_learning import TravelLearning
        model=TravelLearning()
        model.record('lane:a',100,day=0)
        self.assertEqual(model.costs_for(0),{})
        self.assertEqual(model.costs_for(1),{'lane:a':100.})
        model.record('lane:a',200,day=1)
        self.assertEqual(model.costs_for(1),{'lane:a':100.})
        self.assertEqual(model.costs_for(2),{'lane:a':125.})

    def test_small_savings_keep_familiar_route(self):
        from route_learning import TravelLearning
        model=TravelLearning()
        for driver in ('one','two','three'):
            self.assertFalse(model.should_switch(driver,100,99))
            self.assertTrue(model.should_switch(driver,100,50))
            self.assertFalse(model.should_switch(driver,0,0))

    def test_pending_observations_and_habits_survive_json(self):
        from route_learning import TravelLearning
        model=TravelLearning();model.record('lane:a',50,day=0)
        model.habits[('car','home','job')]={'day':0,'edges':['lane:a'],'origin':0,'target':0,'direct':False}
        recovered=TravelLearning.from_dict(json.loads(json.dumps(model.to_dict())))
        self.assertEqual(recovered.habits,model.habits)
        self.assertEqual(recovered.costs_for(1),{'lane:a':50.})

    def test_invalid_observations_and_saved_values_are_rejected(self):
        from route_learning import TravelLearning
        for value in (-1,float('nan'),float('inf')):
            with self.subTest(value=value),self.assertRaises(ValueError):TravelLearning().record('lane:a',value,day=0)
        with self.assertRaises(ValueError):TravelLearning.from_dict({'estimates':{'bad':-2}})

    def test_remaining_route_index_drops_passed_links_and_completed_vehicles(self):
        from route_learning import TravelLearning
        model=TravelLearning();model.track('car',['a','b','b','c'])
        self.assertEqual(model.affected_vehicles('b'),{'car'})
        model.passed('car','a');self.assertEqual(model.affected_vehicles('a'),set())
        model.passed('car','b');self.assertEqual(model.affected_vehicles('b'),{'car'})
        model.finish('car');self.assertEqual(model.affected_vehicles('b'),set())
