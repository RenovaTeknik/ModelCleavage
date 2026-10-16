import sys, pathlib, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
import numpy as np
import manifold3d as mf
from cutting_engine.engine import clean_microscopic_components

class CleanupTests(unittest.TestCase):
    def test_speck_removed_and_cavity_filled(self):
        body=mf.Manifold.cube([10,10,10])
        cavity=mf.Manifold.cube([.05,.05,.05]).translate([5,5,5])
        speck=mf.Manifold.cube([.05,.05,.05]).translate([20,0,0])
        cleaned, report=clean_microscopic_components((body-cavity)+speck)
        self.assertEqual(len(report),2)
        self.assertEqual({x['action'] for x in report},{'removed speck','filled cavity'})
        self.assertAlmostEqual(cleaned.volume(),1000)
        self.assertEqual(len(cleaned.decompose()),1)
    def test_long_thin_feature_and_large_cavity_preserved(self):
        body=mf.Manifold.cube([10,10,10])-mf.Manifold.cube([1,1,1]).translate([5,5,5])
        long=mf.Manifold.cube([2,.001,.001]).translate([20,0,0])
        cleaned,report=clean_microscopic_components(body+long)
        self.assertEqual(report,[])
        self.assertEqual(len(cleaned.decompose()),3)
    def test_only_bounded_submicron_base_sliver_is_removed_when_enabled(self):
        body=mf.Manifold.cube([10,10,10])
        sliver=mf.Manifold.cube([2,.03,.000001]).translate([20,0,0])
        pin=mf.Manifold.cube([2,.001,.001]).translate([30,0,0])
        ordinary,report=clean_microscopic_components(body+sliver+pin)
        self.assertEqual(report,[])
        cleaned,report=clean_microscopic_components(body+sliver+pin,detached_base_slivers=True)
        self.assertEqual(len(report),1)
        self.assertTrue(report[0]['detached_base_sliver'])
        self.assertEqual(len(cleaned.decompose()),2)

    def test_aggregate_budget_enforced(self):
        pieces=[mf.Manifold.cube([.09,.09,.09]).translate([i,0,0]) for i in range(20)]
        with self.assertRaisesRegex(ValueError,'allowance'):
            clean_microscopic_components(mf.Manifold.compose(pieces))

    def test_profile_grid_speck_cleanup_has_separate_bounded_budget(self):
        body=mf.Manifold.cube([10,10,10])
        speck=mf.Manifold.cube([.17,.17,.17]).translate([20,0,0])
        ordinary,report=clean_microscopic_components(body+speck)
        self.assertEqual(report,[])
        corrected,report=clean_microscopic_components(body+speck,profile_resolution=.1)
        self.assertEqual(len(report),1)
        self.assertAlmostEqual(corrected.volume(),body.volume())
        excessive=mf.Manifold.compose([body]+[speck.translate([i,0,0]) for i in range(6)])
        with self.assertRaisesRegex(ValueError,'allowance'):
            clean_microscopic_components(excessive,profile_resolution=.1)
