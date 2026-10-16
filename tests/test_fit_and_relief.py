import sys,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
import numpy as np
import manifold3d as mf
from cutting_engine.engine import CutParameters,cut_region,mesh
from cutting_engine.relief import relieve_prismatic_skins
from cutting_engine.model import load_3mf
import test_engine
class FitAndReliefTests(unittest.TestCase):
    def test_zero_means_minimum_and_targets_split_gap(self):
        model=load_3mf(test_engine.fixture());region=next(r['id'] for r in model.regions if r['state']==2)
        results={}
        for target in ['body','part','both']:
            a=cut_region(model,CutParameters(region,'-Y',-5,2,mode='interface',fit_target=target))
            results[target]=a;fit=a.report['fit_allowances']
            self.assertEqual(a.parameters.side_clearance,0)
            self.assertEqual(fit['effective_side_mm'],.05);self.assertEqual(fit['effective_depth_mm'],.05)
            self.assertAlmostEqual(fit['body_side_mm']+fit['part_side_mm'],.05)
            self.assertAlmostEqual(fit['body_depth_mm']+fit['part_depth_mm'],.05)
            self.assertEqual(a.report['painted_surface_coverage']['missing_samples'],0)
        self.assertLess(results['part'].extracted.volume(),results['body'].extracted.volume())
        self.assertGreater(results['part'].remainder.volume(),results['body'].remainder.volume())
        self.assertEqual(results['both'].report['fit_allowances']['part_side_mm'],.025)
    def test_larger_allowance_not_increased_by_hidden_baseline(self):
        model=load_3mf(test_engine.fixture());region=next(r['id'] for r in model.regions if r['state']==2)
        a=cut_region(model,CutParameters(region,'-Y',-5,2,side_clearance=.2,depth_clearance=.1,mode='interface',fit_target='both'))
        fit=a.report['fit_allowances'];self.assertEqual(fit['body_side_mm'],.1);self.assertEqual(fit['part_side_mm'],.1)
        self.assertEqual(fit['body_depth_mm'],.05)
    def test_angled_generated_fin_removed_but_intrinsic_thin_feature_protected(self):
        source=mf.Manifold.cube([10,10,5])
        body=mf.Manifold.cube([5,5,5])
        fin=mf.Manifold.cube([.005,5,5]).translate([4,4,0])
        n=np.array([0.,0.,1.])
        original=body+fin
        cleaned,relief,records=relieve_prismatic_skins(original,mesh(source),n,0)
        self.assertTrue(records);self.assertGreater(relief.volume(),.01)
        self.assertLess(abs(cleaned.volume()-body.volume()),.01)
        untouched,_,_=relieve_prismatic_skins(body,mesh(source),n,0)
        self.assertAlmostEqual(untouched.volume(),body.volume(),places=6)
        angle=mf.Manifold.cube([.005,5,5]).rotate([0,0,30]).translate([4,4,0])
        cleaned,relief,records=relieve_prismatic_skins(body+angle,mesh(source),n,0)
        self.assertTrue(records)
        intrinsic=body+fin
        cleaned,relief,records=relieve_prismatic_skins(intrinsic,mesh(intrinsic),n,0)
        self.assertAlmostEqual(cleaned.volume(),intrinsic.volume(),places=5)
    def test_round_source_roundoff_does_not_protect_generated_fin(self):
        source=mf.Manifold.cylinder(5,10,circular_segments=97)
        body=mf.Manifold.cube([5,5,5]).translate([-2.5,-2.5,0])
        fin=mf.Manifold.cube([.005,4,5]).translate([2,1,0])
        cleaned,relief,records=relieve_prismatic_skins(body+fin,mesh(source),np.array([0.,0.,1.]),0)
        self.assertTrue(records)
        self.assertGreater(relief.volume(),.05)
        self.assertLess(abs(cleaned.volume()-body.volume()),.01)
    def test_part_allowance_continues_above_lowest_nonplanar_seam(self):
        from cutting_engine.interface import interface_sweep
        from shapely.geometry import Polygon,Point
        from functools import reduce
        selected=np.array([[[-2,-2,0],[2,-2,2],[2,2,2]],[[-2,-2,0],[2,2,2],[-2,2,0]]],float)
        n=np.array([0.,0.,1.])
        solid,_=interface_sweep(selected,n,2,root_inset=.2)
        # At each height the right edge is still hidden behind the sloping
        # painted seam. Its clearance must not reset at the lowest seam point.
        for height in [-.5,.5,1.5]:
            rings=[Polygon(r) for r in solid.slice(height).to_polygons()]
            section=reduce(lambda a,b:a.symmetric_difference(b),rings,Polygon())
            self.assertFalse(section.contains(Point(1.95,0)),height)
            self.assertTrue(section.contains(Point(1.7,0)),height)
        # Original painted surface remains supported by its full front sweep.
        self.assertTrue(solid.ray_cast([1.95,0,2],[1.95,0,1.9]))
    def test_taper_continues_above_lowest_nonplanar_seam(self):
        from cutting_engine.interface import interface_sweep
        selected=np.array([[[-2,-2,0],[2,-2,2],[2,2,2]],[[-2,-2,0],[2,2,2],[-2,2,0]]],float)
        solid,details=interface_sweep(selected,np.array([0.,0.,1.]),2,taper_degrees=3)
        # Probe the hidden right flank above and below the lowest seam.
        right=[]
        for z in [-1.,-.5,.5,1.]:
            section=solid.slice(z)
            right.append(max(p[0] for ring in section.to_polygons() for p in ring))
        for a,b,za,zb in zip(right[:-1],right[1:],[-1.,-.5,.5],[-.5,.5,1.]):
            self.assertAlmostEqual((b-a)/(zb-za),np.tan(np.deg2rad(3)),places=5)
        self.assertAlmostEqual(details['root_tip']['full_mating_span_mm'],4)
    def test_part_clearance_may_trim_only_the_allowed_seam_band(self):
        from cutting_engine.engine import assert_painted_surface_preserved
        selected=np.array([[[-1,-1,0],[1,-1,0],[1,1,0]],[[-1,-1,0],[1,1,0],[-1,1,0]]],float)
        source=mf.Manifold.cube([2,2,1]).translate([-1,-1,-1])
        part=mf.Manifold.cube([1.95,2,1]).translate([-.95,-1,-1])
        with self.assertRaises(ValueError):assert_painted_surface_preserved(selected,part,source)
        report=assert_painted_surface_preserved(selected,part,source,seam_allowance=.1)
        self.assertGreater(report['excluded_fit_seam_samples'],0)
        self.assertEqual(report['missing_samples'],0)
        missing_interior=mf.Manifold.cube([1,2,1]).translate([0,-1,-1])
        with self.assertRaises(ValueError):assert_painted_surface_preserved(selected,missing_interior,source,seam_allowance=.1)
    def test_seven_degree_taper_starts_on_each_point_of_the_paint_seam(self):
        from cutting_engine.interface import interface_sweep
        selected=np.array([[[-2,-2,0],[2,-2,2],[2,2,2]],[[-2,-2,0],[2,2,2],[-2,2,0]]],float)
        solid,details=interface_sweep(selected,np.array([0.,0.,1.]),2,taper_degrees=7)
        # The lowest seam point must remain at the mouth, rather than inherit
        # two millimetres of taper from the highest point of this sloped seam.
        ring=np.vstack(solid.slice(-.001).to_polygons())
        self.assertLess(abs(ring[:,0].min()+2.005),.001)
        self.assertAlmostEqual(ring[:,0].max(),2.005-2.001*np.tan(np.deg2rad(7)),delta=.01)
        self.assertTrue(details['root_tip']['seam_anchored'])
    def test_invalid_target_rejected(self):
        with self.assertRaises(ValueError):CutParameters(0,'+Z',0,fit_target='invalid').validate()
