"""Immutable shared route trees must preserve directed weighted reachability."""
import concurrent.futures
import importlib.util
import unittest


class NativeRoutingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('native_routing'), 'Native route trees are not implemented')

    def graph(self):
        from native_routing import NativeRouteGraph
        # The cheap 0->1->3 branch beats 0->2->3; node 4 is disconnected.
        return NativeRouteGraph(5, [(0,1,2.),(1,3,3.),(0,2,1.),(2,3,9.)])

    def test_tree_reuses_shortest_paths_from_different_origins(self):
        graph=self.graph();tree=graph.tree([(3,0.)])
        self.assertEqual(tree.path([(0,0.)]),(0,0,(0,1),5.))
        self.assertEqual(tree.path([(1,0.)]),(0,0,(1,),3.))
        self.assertIsNone(tree.path([(4,0.)]))
        self.assertIsNone(graph.tree([(0,0.)]).path([(3,0.)]))

    def test_cost_only_queries_match_paths_and_validate_origins(self):
        tree=self.graph().tree([(1,10.),(3,1.)])
        for origins in ([(0,8.),(2,0.)],[(3,4.)],[(4,0.)]):
            path=tree.path(origins)
            self.assertEqual(tree.cost(origins),path[3] if path else float('inf'))
        for origins in ([],[(-1,0.)],[(0,float('inf'))]):
            with self.assertRaises(ValueError):tree.cost(origins)

    def test_multiple_roots_and_initial_costs_choose_global_minimum(self):
        tree=self.graph().tree([(1,10.),(3,1.)])
        self.assertEqual(tree.path([(0,8.),(2,0.)]),(1,1,(3,),10.))
        self.assertEqual(tree.path([(3,4.)]),(0,1,(),5.))

    def test_query_buffers_are_independent_across_threads(self):
        tree=self.graph().tree([(3,0.)])
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            rows=list(pool.map(lambda n:tree.path([(n%2,0.)]),range(40)))
        self.assertEqual(rows[::2],[(0,0,(0,1),5.)]*20)
        self.assertEqual(rows[1::2],[(0,0,(1,),3.)]*20)

    def test_zero_cost_cycles_terminate_and_graph_outlives_tree_factory(self):
        from native_routing import NativeRouteGraph
        tree=NativeRouteGraph(3,[(0,1,0.),(1,0,0.),(1,2,2.)]).tree([(2,0.)])
        self.assertEqual(tree.path([(0,0.)]),(0,0,(0,2),2.))

    def test_invalid_inputs_are_rejected_without_native_memory_errors(self):
        from native_routing import NativeRouteGraph
        for rows in ([(0,5,1.)],[(0,1,-1.)],[(0,1,float('nan'))]):
            with self.subTest(rows=rows),self.assertRaises(ValueError):NativeRouteGraph(2,rows)
        graph=self.graph()
        with self.assertRaises(ValueError):graph.tree([(8,0.)])
        with self.assertRaises(ValueError):graph.tree([(3,0.)],costs=[1.])
        with self.assertRaises(ValueError):graph.tree([(3,0.)]).path([(-1,0.)])
        with self.assertRaises(ValueError):graph.tree([(3,0.)]).path([(0,float('inf'))])

    def test_weight_snapshot_changes_only_the_new_tree(self):
        graph=self.graph();old=graph.tree([(3,0.)])
        new=graph.tree([(3,0.)],costs=[2.,30.,1.,9.])
        self.assertEqual(new.path([(0,0.)]),(0,0,(2,3),10.))
        self.assertEqual(old.path([(0,0.)]),(0,0,(0,1),5.))
