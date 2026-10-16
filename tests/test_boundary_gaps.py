import sys,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
import numpy as np
from cutting_engine.interface import close_boundary_gaps
class BoundaryGapTests(unittest.TestCase):
    def test_short_supported_gap_closes(self):
        v=np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,.02,0]],float)
        e=np.array([[0,1],[1,2],[2,3],[3,4]])
        surface=v[np.array([[0,1,2],[0,2,3]])]
        corrected,report=close_boundary_gaps(v,e,surface)
        self.assertEqual(report['count'],1);self.assertAlmostEqual(report['lengths_mm'][0],.02)
        self.assertTrue(np.all(np.bincount(corrected.ravel())%2==0))
    def test_large_gap_rejected(self):
        v=np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,.2,0]],float)
        e=np.array([[0,1],[1,2],[2,3],[3,4]])
        with self.assertRaisesRegex(ValueError,'too large'):
            close_boundary_gaps(v,e,v[np.array([[0,1,2],[0,2,3]])])
    def test_gap_not_supported_by_paint_rejected(self):
        v=np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,.02,0]],float)
        e=np.array([[0,1],[1,2],[2,3],[3,4]])
        with self.assertRaisesRegex(ValueError,'leaves the painted surface'):
            close_boundary_gaps(v,e,np.array([[[10,0,0],[11,0,0],[10,1,0]]],float))
