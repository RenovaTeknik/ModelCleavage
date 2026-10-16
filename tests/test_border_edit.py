import sys,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
import numpy as np
from cutting_engine.model import load_3mf
from cutting_engine.border_edit import smooth_border
from cutting_engine.interface import paint_boundary
from cutting_engine.engine import cut_region,CutParameters
class BorderEditTests(unittest.TestCase):
    def setUp(self):
        self.model=load_3mf((ROOT/'tests/fixtures/curved-interface.3mf').read_bytes())
        self.region=next(r['id'] for r in self.model.regions if r['state']==2)
    def test_bounded_shared_surface_edit_and_original_unchanged(self):
        m=self.model; before=m.source.vertices.copy();paint=m.triangles.copy()
        c,r=smooth_border(m,self.region,.1,1)
        self.assertTrue(c.cut_ready);self.assertGreater(r['moved_vertices'],0)
        self.assertLessEqual(r['maximum_movement_mm'],.1+1e-12)
        np.testing.assert_array_equal(m.source.vertices,before);np.testing.assert_array_equal(m.triangles,paint)
        # Every leaf stays on its parent; the two colours share exact positions.
        import trimesh
        parent=c.source.triangles[c.paint_parents]
        for i in range(3):
            bary=trimesh.triangles.points_to_barycentric(parent,c.triangles[:,i])
            np.testing.assert_allclose(np.einsum('ni,nij->nj',bary,parent),c.triangles[:,i],atol=1e-10)
        for colour in [1,2]:
            p,e=paint_boundary(c.triangles[c.states==colour])
            keys={tuple(v) for v in p[np.unique(e)]}
            if colour==1:first=keys
            else:self.assertEqual(first,keys)
        fixed=before[:,2]<=m.source.bounds[0,2]+.005
        np.testing.assert_array_equal(c.source.vertices[fixed],before[fixed])
        self.assertIsNone(c.archive_source)
    def test_smoothed_model_still_cuts_with_paint_coverage(self):
        c,r=smooth_border(self.model,self.region,.1,1)
        result=cut_region(c,CutParameters(self.region,'+Z',0,1,mode='interface'))
        self.assertEqual(result.report['painted_surface_coverage']['missing_samples'],0)
        self.assertLess(result.report['insertion_path']['max_overlap_mm3'],.001)
    def test_invalid_parameters_rejected(self):
        for amount,band in [(0,1),(.6,1),(.1,0),(float('nan'),1)]:
            with self.assertRaises(ValueError):smooth_border(self.model,self.region,amount,band)
