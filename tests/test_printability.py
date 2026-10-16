import sys,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
import numpy as np
import manifold3d as mf
from cutting_engine.printability import filter_cut_fragments,absorb_fragments
from cutting_engine.engine import CutParameters
class PrintabilityTests(unittest.TestCase):
    def test_cut_strip_absorbed_without_losing_material(self):
        source=mf.Manifold.cube([10,10,10]);left=mf.Manifold.cube([5,10,10])
        strip=mf.Manifold.cube([.05,2,2]).translate([6,0,0])
        base=left+strip;part=source-base
        corrected,fragments,records=filter_cut_fragments(base,source,.2)
        self.assertEqual(len(records),1);self.assertAlmostEqual(records[0]['enclosing_width_mm'],.05)
        merged,_=absorb_fragments(part,fragments)
        self.assertEqual(len(corrected.decompose()),1);self.assertEqual(len(merged.decompose()),1)
        self.assertAlmostEqual((source-(corrected+merged)).volume(),0,places=8)
        self.assertAlmostEqual((corrected^merged).volume(),0,places=8)
    def test_preexisting_thin_separate_feature_is_preserved(self):
        body=mf.Manifold.cube([10,10,10]);pin=mf.Manifold.cube([.02,2,2]).translate([12,0,0])
        source=body+pin;base=mf.Manifold.cube([5,10,10])+pin
        corrected,fragments,records=filter_cut_fragments(base,source,.2)
        self.assertEqual(records,[]);self.assertEqual(len(corrected.decompose()),2)
    def test_disabled_filter_and_printable_piece_preserved(self):
        source=mf.Manifold.cube([10,10,10]);piece=mf.Manifold.cube([.3,2,2]).translate([6,0,0]);base=mf.Manifold.cube([5,10,10])+piece
        for width in [0,.2]:
            _,fragments,records=filter_cut_fragments(base,source,width)
            self.assertEqual(records,[])
    def test_rotated_thin_strip_detected(self):
        body=mf.Manifold.cube([10,10,10]);strip=mf.Manifold.cube([.02,2,2]).rotate([20,30,40]).translate([12,0,0]);source=body+mf.Manifold.cube([4,4,4]).translate([11,-1,-1])
        _,fragments,records=filter_cut_fragments(body+strip,source,.2)
        self.assertEqual(len(records),1);self.assertLess(records[0]['enclosing_width_mm'],.021)
    def test_invalid_width_rejected(self):
        for width in [-.1,1.1,float('nan')]:
            with self.assertRaises(ValueError):CutParameters(0,'+Z',0,1,minimum_fragment_width_mm=width).validate()
