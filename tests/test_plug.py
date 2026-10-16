import pathlib,sys,unittest,math
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
import numpy as np
from shapely.geometry import box
from cutting_engine.root_profile import tapered_root
from cutting_engine.engine import mesh,CutParameters,cut_region
import test_interface as interface_tests

class PlugTests(unittest.TestCase):
 def test_angle_reduces_tip_by_depth_times_tangent(self):
  shape=box(-3,-2,3,2);root,report=tapered_root(shape,0,2,2,2,3)
  self.assertTrue(mesh(root).is_watertight)
  tip=np.vstack(root.slice(-2+1e-6).to_polygons());amount=2*math.tan(math.radians(3))
  np.testing.assert_allclose(tip.min(0),[-3+amount,-2+amount],atol=1e-6)
  np.testing.assert_allclose(tip.max(0),[3-amount,2-amount],atol=1e-6)
 def test_shared_bottom_stays_fixed_while_other_walls_taper(self):
  root,report=tapered_root(box(-3,-2,3,2),0,2,2,2,3,protected_plane=([0,1],-2))
  tip=np.vstack(root.slice(-2+1e-6).to_polygons());amount=2*math.tan(math.radians(3))
  self.assertAlmostEqual(tip[:,1].min(),-2,places=7)
  self.assertAlmostEqual(tip[:,1].max(),2-amount,places=6)
 def test_extra_depth_does_not_shrink_nominal_tip(self):
  nominal,_=tapered_root(box(-3,-2,3,2),0,2,2,2,3)
  pocket,_=tapered_root(box(-3,-2,3,2),0,2,2,2.2,3)
  self.assertAlmostEqual((nominal-pocket).volume(),0,places=7)
  self.assertAlmostEqual(mesh(pocket).bounds[0,2],-2.2,places=7)
 def test_smoothed_tapered_curved_feature_preserves_paint_and_withdrawal(self):
  interface_tests.InterfaceTests.setUpClass()
  result=cut_region(interface_tests.InterfaceTests.model,CutParameters(1,'+Z',0,1,mode='interface',root_taper_degrees=3,root_smoothing_mm=.15))
  self.assertEqual(result.report['painted_surface_coverage']['missing_samples'],0)
  self.assertLess(result.report['insertion_path']['max_overlap_mm3'],.001)
  self.assertFalse(result.report['interface']['shared_bottom_preserved'])
 def test_taper_consuming_tip_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'tip'):
   tapered_root(box(-.05,-.05,.05,.05),0,2,2,2,15)

if __name__=='__main__':unittest.main()
