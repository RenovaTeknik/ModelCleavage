import sys,pathlib,unittest,math
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
import numpy as np
import manifold3d as mf
from cutting_engine.engine import CutParameters,mesh,cut_region
from cutting_engine.glue import glue_pockets,frustum
from cutting_engine.model import load_3mf
class GlueTests(unittest.TestCase):
    def cubes(self,gap=0):
        return mf.Manifold.cube([8,8,4]).translate([-4,-4,0]),mf.Manifold.cube([8,8,4]).translate([-4,-4,-4-gap])
    def test_paired_undercuts_have_exact_volume_and_remain_solid(self):
        a,b=self.cubes();p=CutParameters(0,'+Z',0,2,mode='interface',fastener='glue')
        x,y,r=glue_pockets(a,b,np.array([0.,0.,1.]),0,p)
        self.assertTrue(r['wall_envelope_checked']);self.assertEqual(r['pairs'],1)
        self.assertGreater(r['interior_mm'][0],r['opening_mm'][0])
        for original,result,removed in zip([a,b],[x,y],r['removed_volume_mm3']):
            self.assertAlmostEqual(removed,r['nominal_volume_each_mm3'],places=7)
            self.assertTrue(mesh(result).is_watertight);self.assertEqual(len(result.decompose()),1)
        # A shallow slab inside either pocket has a wider cavity than its mouth.
        for solid,sign in [(x,1),(y,-1)]:
            centre=np.array(r['opening_centres_mm'][0]);t=math.tan(math.radians(5))
            probe=mf.Manifold.cube([.01,.01,.01]).translate(centre+np.array([0,-1.5-.3*t+.005,sign*.3-.005]))
            self.assertLess(abs((solid^probe).volume()),1e-8)
    def test_clearance_keeps_openings_aligned(self):
        a,b=self.cubes(.2);p=CutParameters(0,'+Z',0,2,mode='interface',fastener='glue',depth_clearance=.2)
        _,_,r=glue_pockets(a,b,np.array([0.,0.,1.]),0,p)
        np.testing.assert_allclose(np.array(r['opening_centres_mm'][0])-r['opening_centres_mm'][1],[0,0,.2])
    def test_insufficient_wall_thickness_rejected(self):
        a,b=self.cubes();a=mf.Manifold.cube([8,8,.7]).translate([-4,-4,0]);p=CutParameters(0,'+Z',0,2,mode='interface',fastener='glue')
        with self.assertRaisesRegex(ValueError,'not enough material'):glue_pockets(a,b,np.array([0.,0.,1.]),0,p)
    def test_small_face_rejected_without_breakthrough(self):
        a=mf.Manifold.cube([1,1,4]);b=a.translate([0,0,-4]);p=CutParameters(0,'+Z',0,2,mode='interface',fastener='glue')
        with self.assertRaisesRegex(ValueError,'do not fit'):glue_pockets(a,b,np.array([0.,0.,1.]),0,p)
    def test_cut_integration_separates_glue_volume_from_fit_gap(self):
        model=load_3mf((ROOT/'tests/fixtures/curved-interface.3mf').read_bytes());region=next(r['id'] for r in model.regions if r['state']==2)
        plain=cut_region(model,CutParameters(region,'+Z',0,1,mode='interface'))
        glue=cut_region(model,CutParameters(region,'+Z',0,1,mode='interface',fastener='glue',glue_depth_mm=.2,glue_wall_mm=.3))
        self.assertTrue(glue.report['glue_keys']['enabled']);self.assertAlmostEqual(glue.report['fit_gap_volume_mm3'],plain.report['fit_gap_volume_mm3'],places=6)
        removed=plain.extracted.volume()+plain.remainder.volume()-glue.extracted.volume()-glue.remainder.volume()
        self.assertAlmostEqual(removed,glue.report['glue_keys']['total_removed_mm3'],places=6)
        self.assertEqual(glue.report['painted_surface_coverage']['missing_samples'],0)
    def test_invalid_settings_and_planar_glue_rejected(self):
        for values in [dict(glue_depth_mm=0),dict(glue_taper_degrees=0),dict(glue_width_mm=float('nan')),dict(glue_wall_mm=.1),dict(mode='planar')]:
            kwargs=dict(mode='interface',fastener='glue');kwargs.update(values)
            with self.assertRaises(ValueError):CutParameters(0,'+Z',0,2,**kwargs).validate()
